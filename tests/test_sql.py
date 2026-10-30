"""SQL lexing: strings, quoted names and dollar-quoted bodies are content, and MySQL files are read the MySQL way."""
import os
import re
import time
import unittest

from agent_comment_lint.lexers import LexError, family_for
from agent_comment_lint.lexers.base import CODE, COMMENT, STRING
from support import LONG, comments, found

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MYSQL = "/*!40101 SET NAMES utf8 */;\n"


def opens(text):
    return [line.opens_in for line in family_for("a.sql").lex(text)]


class TestScope(unittest.TestCase):
    def test_the_sql_extension_is_covered(self):
        self.assertEqual(family_for("db/schema.sql").name, "sql")
        self.assertEqual(found("db/schema.sql", "-- see ADR-9\n"), [("C3", 1)])

    def test_the_pre_commit_filter_matches_sql_files(self):
        with open(os.path.join(REPO, ".pre-commit-hooks.yaml"), encoding="utf-8") as handle:
            filters = re.findall(r"^\s*files: (.+)$", handle.read(), flags=re.M)
        self.assertEqual(len(filters), 2)
        self.assertEqual(filters[0], filters[1])
        self.assertTrue(re.search(filters[0], "db/schema.sql"))
        self.assertFalse(re.search(filters[0], "db/schema.sqlite"))


class TestDialect(unittest.TestCase):
    def test_a_file_without_a_marker_is_read_as_standard_sql(self):
        self.assertEqual(comments("a.sql", "SELECT 1--1;\n"), [["--1;"]])

    def test_an_executable_comment_switches_to_mysql(self):
        self.assertEqual(comments("a.sql", MYSQL + "SELECT 1--1;\n"), [[], []])

    def test_a_backtick_identifier_switches_to_mysql(self):
        self.assertEqual(comments("a.sql", "SELECT 1--1;\nSELECT `a` FROM t;\n"), [[], []])

    def test_a_delimiter_line_switches_to_mysql(self):
        text = ("DELIMITER $$\nCREATE PROCEDURE a() BEGIN SELECT 1; END $$\n"
                "CREATE PROCEDURE b() BEGIN SELECT 2; END $$\nDELIMITER ;\n")
        self.assertEqual(found("a.sql", text), [])
        text = "SELECT 1;\n  delimiter //\nCREATE PROCEDURE a() BEGIN SELECT 1--1; END //\n"
        self.assertEqual(comments("a.sql", text), [[], [], []])

    def test_markers_inside_strings_and_comments_do_not_switch(self):
        text = "-- uses `a` and /*! x */\nSELECT '`b`', \"/*!\", 1--1;\n/* `c`\nDELIMITER $$ */\n"
        self.assertEqual(comments("a.sql", text), [["-- uses `a` and /*! x */"], ["--1;"], ["/* `c`"],
                                                   ["DELIMITER $$ */"]])

    def test_markers_inside_a_dollar_quoted_body_do_not_switch(self):
        text = "SELECT $$ `a` /*! b */ $$, 1--1;\nSELECT $$\nDELIMITER $x$\n$$;\n"
        self.assertEqual(comments("a.sql", text), [["--1;"], [], [], []])

    def test_a_delimiter_option_inside_a_statement_does_not_switch(self):
        text = "COPY t FROM '/x.csv'\nDELIMITER ','\nCSV;\nSELECT $$it's$$, 1--1;\n"
        self.assertEqual(comments("a.sql", text), [[], [], [], ["--1;"]])

    def test_a_mysql_escape_before_the_first_marker_is_read_the_mysql_way(self):
        text = "INSERT INTO t VALUES ('it\\'s');\nSELECT `a` FROM t; -- see ADR-9\n"
        self.assertEqual(found("a.sql", text), [("C3", 2)])

    def test_a_file_the_mysql_reading_finds_no_marker_in_keeps_the_standard_error(self):
        with self.assertRaises(LexError) as caught:
            found("a.sql", "SELECT 'it\\'s';\nSELECT 1;\n")
        self.assertEqual(caught.exception.line, 1)
        with self.assertRaises(LexError) as caught:
            found("a.sql", "SELECT 'it\\'s';\nSELECT `a\n")
        self.assertEqual(caught.exception.line, 1)

    def test_a_delimiter_after_a_comment_still_switches(self):
        text = "SELECT 1; -- one\n/* two */\nDELIMITER $$\nCREATE PROCEDURE a() BEGIN SELECT 1--1; END $$\n"
        self.assertEqual(comments("a.sql", text), [["-- one"], ["/* two */"], [], []])


class TestDashComments(unittest.TestCase):
    def test_two_dash_lines_are_one_block(self):
        self.assertEqual(found("a.sql", "-- one\n-- two\nSELECT 1;\n"), [("C1", 1)])

    def test_a_trailing_comment_is_read(self):
        self.assertEqual(found("a.sql", "SELECT 1; -- see ADR-9\n"), [("C3", 1)])

    def test_a_trailing_comment_joins_no_block(self):
        self.assertEqual(found("a.sql", "SELECT 1; -- one\n-- two\nSELECT 2;\n"), [])

    def test_a_blank_line_splits_a_block(self):
        self.assertEqual(found("a.sql", "-- one\n\n-- two\n"), [])

    def test_an_overlong_comment_line_is_reported(self):
        self.assertEqual(found("a.sql", "SELECT 1; -- %s\n" % LONG), [("C7", 1)])

    def test_a_dash_pair_needs_a_space_or_a_line_end_in_mysql(self):
        text = MYSQL + "SELECT 1--1;\nSELECT 1 -- one\nSELECT 1\t--\ttwo\nSELECT 1 --\nSELECT 1 --- three\n"
        self.assertEqual(comments("a.sql", text), [[], [], ["-- one"], ["--\ttwo"], ["--"], ["-- three"]])


class TestHashComments(unittest.TestCase):
    def test_json_operators_are_code(self):
        self.assertEqual(found("a.sql", "SELECT d #> '{a,b}', d #>> '{c}' FROM t;\n"), [])
        self.assertEqual(comments("a.sql", "SELECT d #- '{a}', #temp FROM t;\n"), [[]])

    def test_a_hash_before_a_space_or_a_line_end_opens_a_comment(self):
        self.assertEqual(found("a.sql", "# one\n# two\nSELECT 1;\n"), [("C1", 1)])
        self.assertEqual(comments("a.sql", "SELECT 1; #\n"), [["#"]])

    def test_a_hash_always_opens_a_comment_in_mysql(self):
        self.assertEqual(found("a.sql", MYSQL + "SELECT 1#see ADR-9\n"), [("C3", 2)])
        self.assertEqual(comments("a.sql", MYSQL + "SELECT d #> '{a}';\n"), [[], ["#> '{a}';"]])


class TestBlockComments(unittest.TestCase):
    def test_a_multi_line_block_comment_is_one_block(self):
        self.assertEqual(found("a.sql", "/*\nTable a holds x.\nIt also y.\n*/\nCREATE TABLE a (x int);\n"), [("C1", 2)])

    def test_a_block_opened_after_code_is_scored_from_its_opening_line(self):
        self.assertEqual(found("a.sql", "SELECT 1; /* one\n two */\n"), [("C1", 1)])

    def test_a_one_line_block_comment_is_read(self):
        self.assertEqual(found("a.sql", "SELECT /* see ADR-9 */ 1;\n"), [("C3", 1)])
        self.assertEqual(found("a.sql", "/* one */\n/* two */\n"), [])

    def test_block_comments_do_not_nest(self):
        self.assertEqual(comments("a.sql", "/* a /* b */ SELECT 1;\n"), [["/* a /* b */"]])

    def test_a_comment_after_a_block_close_starts_a_block(self):
        self.assertEqual(found("a.sql", "/* a\n b */ -- c\n-- d\n"), [("C1", 1), ("C1", 2)])
        self.assertEqual(found("a.sql", "/* a\n */ -- c\n"), [])

    def test_a_comment_after_code_after_a_block_close_joins_no_block(self):
        self.assertEqual(found("a.sql", "/* a\n */ SELECT 1; -- b\n-- c\n"), [])
        self.assertEqual(found("a.sql", "/* a\n */ /* b */ -- c\n-- d\n"), [])

    def test_an_executable_comment_is_code(self):
        self.assertEqual(comments("a.sql", MYSQL), [[]])
        self.assertEqual(found("a.sql", "/*!50003 CREATE see ADR-9 '%s' */;\n" % LONG), [])

    def test_an_optimizer_hint_is_code(self):
        self.assertEqual(found("a.sql", "SELECT /*+ see ADR-9 %s */ 1;\n" % LONG), [])
        self.assertEqual(comments("a.sql", "SELECT /*+ SeqScan(t) */ 1;\n"), [[]])

    def test_the_lines_an_executable_comment_spans_open_in_a_string(self):
        text = "/*!50003 CREATE\n-- one\n-- two\n*/;\nSELECT /*+\n see ADR-9 */ 1;\n"
        self.assertEqual(found("a.sql", text), [])
        self.assertEqual(opens(text), [CODE, STRING, STRING, STRING, CODE, STRING])

    def test_a_comment_after_an_executable_comment_joins_no_block(self):
        self.assertEqual(found("a.sql", "/*!50003 CREATE\n*/ -- one\n-- two\n"), [])

    def test_an_unterminated_block_comment_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found("a.sql", "SELECT 1;\n/* x\n-- see ADR-9\n")
        self.assertEqual((caught.exception.line, caught.exception.message), (2, "unterminated block comment"))


class TestStrings(unittest.TestCase):
    def test_a_dash_pair_in_a_string_is_content(self):
        self.assertEqual(found("a.sql", "SELECT '-- see ADR-9';\n"), [])

    def test_a_doubled_quote_is_a_quote(self):
        self.assertEqual(comments("a.sql", "SELECT 'it''s -- x' -- see ADR-9\n"), [["-- see ADR-9"]])

    def test_a_multi_line_string_is_content(self):
        self.assertEqual(found("a.sql", "SELECT 'a\n-- see ADR-9\n';\n-- see ADR-8\n"), [("C3", 4)])

    def test_the_lines_a_string_spans_open_in_a_string(self):
        self.assertEqual(opens("SELECT 'a\n-- one\n-- two\n';\n"), [CODE, STRING, STRING, STRING])
        self.assertEqual(found("a.sql", "SELECT 'a\n-- one\n-- two\n';\n"), [])

    def test_a_backslash_is_literal_in_standard_sql(self):
        self.assertEqual(found("a.sql", "SELECT 'C:\\' -- see ADR-9\n"), [("C3", 1)])

    def test_a_backslash_escapes_in_an_e_string(self):
        self.assertEqual(found("a.sql", "SELECT E'it\\'s -- x' -- see ADR-9\n"), [("C3", 1)])
        self.assertEqual(found("a.sql", "SELECT e'it\\'s -- x' -- see ADR-9\n"), [("C3", 1)])

    def test_a_word_that_ends_in_e_opens_no_e_string(self):
        self.assertEqual(comments("a.sql", "SELECT * FROM t WHERE'C:\\' -- see ADR-9\n"), [["-- see ADR-9"]])

    def test_a_backslash_escapes_in_mysql(self):
        self.assertEqual(comments("a.sql", MYSQL + "SELECT 'it\\'s -- x', \"a\\\"b -- y\" -- see ADR-9\n"),
                         [[], ["-- see ADR-9"]])

    def test_a_mysqldump_line_is_code(self):
        self.assertEqual(found("a.sql", "/*!40101 SET NAMES utf8 */;\nINSERT INTO `t` VALUES ('it\\'s -- x');\n"), [])

    def test_string_prefixes_are_plain_letters(self):
        text = "SELECT N'a--', X'0F', B'01', U&'d\\0061t--a', n'C:\\' -- see ADR-9\n"
        self.assertEqual(comments("a.sql", text), [["-- see ADR-9"]])

    def test_an_unterminated_string_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found("a.sql", "SELECT 'x\n")
        self.assertEqual(caught.exception.line, 1)

    def test_an_unterminated_escaped_string_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found("a.sql", "SELECT 1;\nSELECT E'x\\'\n;\n")
        self.assertEqual(caught.exception.line, 2)
        with self.assertRaises(LexError) as caught:
            found("a.sql", MYSQL + "SELECT 'x\\'\n;\n")
        self.assertEqual(caught.exception.line, 2)


class TestQuotedIdentifiers(unittest.TestCase):
    def test_a_quoted_identifier_is_content(self):
        self.assertEqual(comments("a.sql", 'SELECT "a--b", "c""--d" FROM t; -- see ADR-9\n'), [["-- see ADR-9"]])

    def test_a_backtick_identifier_is_content(self):
        self.assertEqual(comments("a.sql", "SELECT `a--b`, `c``#d` FROM t; -- see ADR-9\n"), [["-- see ADR-9"]])

    def test_a_bracketed_identifier_is_code(self):
        self.assertEqual(comments("a.sql", "SELECT [a b] FROM t; -- see ADR-9\n"), [["-- see ADR-9"]])

    def test_an_unterminated_quoted_identifier_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found("a.sql", 'SELECT 1;\nSELECT "a\n')
        self.assertEqual((caught.exception.line, caught.exception.message), (2, "unterminated quoted identifier"))

    def test_an_unterminated_backtick_identifier_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found("a.sql", "SELECT 1;\nSELECT `a\n")
        self.assertEqual((caught.exception.line, caught.exception.message), (2, "unterminated quoted identifier"))


class TestDollarQuoting(unittest.TestCase):
    def test_a_plpgsql_comment_is_judged(self):
        text = "CREATE FUNCTION f() RETURNS int AS $$\nBEGIN\n  -- see ADR-9\n  RETURN 1;\nEND;\n$$ LANGUAGE plpgsql;\n"
        self.assertEqual(found("a.sql", text), [("C3", 3)])

    def test_a_plpgsql_comment_block_is_judged(self):
        text = "CREATE FUNCTION f() RETURNS int AS $body$\n  -- one\n  -- two\n  /* three\n  four */\n$body$;\n"
        self.assertEqual(found("a.sql", text), [("C1", 2), ("C1", 4)])

    def test_a_dollar_body_that_does_not_lex_is_content(self):
        self.assertEqual(found("a.sql", "SELECT $$it's$$;\n-- see ADR-9\n"), [("C3", 2)])

    def test_the_lines_of_a_body_that_does_not_lex_open_in_a_string(self):
        text = "SELECT $$\n-- one\n-- two\nit's\n$$;\n"
        self.assertEqual(found("a.sql", text), [])
        self.assertEqual(opens(text), [CODE, STRING, STRING, STRING, STRING])

    def test_a_comment_in_a_body_ends_with_the_body(self):
        self.assertEqual(comments("a.sql", "SELECT $$ SELECT 1 -- x $$, 2; -- see ADR-9\n"),
                         [["-- x ", "-- see ADR-9"]])

    def test_a_tagged_dollar_quote_closes_only_on_its_own_tag(self):
        text = ("CREATE FUNCTION f() RETURNS void AS $fn$\nBEGIN\n  EXECUTE $q$ SELECT 'it''s' $q$;\n"
                "  PERFORM $$ it's $$;\n  -- see ADR-9\nEND;\n$fn$ LANGUAGE plpgsql;\n")
        self.assertEqual(found("a.sql", text), [("C3", 5)])

    def test_a_body_that_does_not_lex_inside_a_body_is_content(self):
        text = "SELECT $a$ $b$ it's $b$ -- see ADR-9\n$a$;\n"
        self.assertEqual(found("a.sql", text), [("C3", 1)])

    def test_a_parameter_or_a_dollar_inside_a_word_opens_nothing(self):
        self.assertEqual(found("a.sql", "SELECT $1, a$b$, c$$ -- see ADR-9\n"), [("C3", 1)])

    def test_a_dollar_quote_opens_nothing_in_mysql(self):
        self.assertEqual(found("a.sql", MYSQL + "SELECT $$ -- see ADR-9\n"), [("C3", 2)])

    def test_an_unterminated_dollar_quote_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found("a.sql", "SELECT 1;\nSELECT $x$ it\n-- see ADR-9\n")
        self.assertEqual((caught.exception.line, caught.exception.message), (2, "unterminated dollar quote"))


class TestLineEndings(unittest.TestCase):
    def test_windows_line_endings_lex_like_newlines(self):
        self.assertEqual(found("a.sql", "-- a\r\n-- b\r\nSELECT 1;\r\n"), found("a.sql", "-- a\n-- b\nSELECT 1;\n"))
        text = ("-- one\n-- two\nSELECT 'a\n-- three\n';\n/* four\n five */\n"
                "CREATE FUNCTION f() AS $$\n-- six\n-- seven\n$$;\n")
        self.assertEqual(found("a.sql", text.replace("\n", "\r\n")), found("a.sql", text))
        self.assertEqual(found("a.sql", text), [("C1", 1), ("C1", 6), ("C1", 9)])


class TestLongInput(unittest.TestCase):
    def test_a_long_line_lexes_quickly(self):
        line = ("SELECT " + "'a''b', \"c\", E'd\\'e', $$f -- g$$, $h$i$h$, a$b, $1, x #> y, /* z */ " * 4000
                + "1; -- see ADR-9\n")
        self.assertGreater(len(line), 250000)
        started = time.perf_counter()
        self.assertEqual(found("a.sql", line), [("C3", 1), ("C7", 1)])
        self.assertLess(time.perf_counter() - started, 5.0)

    def test_many_bodies_that_do_not_lex_are_quick(self):
        started = time.perf_counter()
        self.assertEqual(found("a.sql", "SELECT $$it's$$;\n" * 20000 + "-- see ADR-9\n"), [("C3", 20001)])
        self.assertLess(time.perf_counter() - started, 5.0)

    def test_a_long_unterminated_string_is_refused_quickly(self):
        started = time.perf_counter()
        with self.assertRaises(LexError):
            found("a.sql", "SELECT 'a" + "''\\" * 100000 + "\n")
        with self.assertRaises(LexError):
            found("a.sql", MYSQL + "SELECT 'a" + "''\\'" * 100000 + "\n")
        self.assertLess(time.perf_counter() - started, 5.0)


if __name__ == "__main__":
    unittest.main()
