"""False positives both earlier copies had, pinned as they are today so that changing one is a decision."""
import unittest

from agent_comment_lint import engine, governance
from agent_comment_lint.lexers import LexError
from support import LONG, comments, found


class TestALeadingStarInLineLexedCode(unittest.TestCase):
    WRAPPED = "var x = a\n    * b\n    * c;\n"

    def test_a_wrapped_multiplication_in_csharp_is_a_prose_block(self):
        self.assertEqual(found("a.cs", self.WRAPPED), [("C1", 2)])

    def test_a_wrapped_multiplication_in_hcl_is_a_prose_block(self):
        self.assertEqual(found("main.tf", "x = a\n    * b\n    * c\n"), [("C1", 2)])


class TestDocsPathHasNoLeftAnchor(unittest.TestCase):
    def test_a_web_address_that_holds_a_docs_segment_is_a_governance_reference(self):
        address = "https://developer.mozilla.org/en-US/docs/Web/API/fetch"
        for path, comment in (("a.ts", "// "), ("a.cs", "// "), ("a.py", "# "), ("a.yml", "# ")):
            self.assertEqual(found(path, comment + address + "\n"), [("C3", 1)], path)


class TestAnyUnquotedHashOpensAComment(unittest.TestCase):
    def test_a_parameter_expansion_that_strips_a_docs_prefix_is_a_governance_reference(self):
        self.assertEqual(found("run.sh", "x=${y#docs/prefix}\n"), [("C3", 1)])
        self.assertEqual(found("pipeline.yml", "  - script: x=${y#docs/prefix}\n"), [("C3", 1)])
        self.assertEqual(found("main.tf", "x = replace(y, #docs/prefix\n"), [("C3", 1)])

    def test_a_long_line_that_counts_its_arguments_is_an_overlong_comment_line(self):
        self.assertEqual(found("run.sh", 'if [ $# -lt 2 ]; then echo "%s"; fi\n' % LONG), [("C7", 1)])
        self.assertEqual(found("pipeline.yml", '  - script: test $# -lt 2 || echo "%s"\n' % LONG), [("C7", 1)])


class TestCsharpVerbatimStringBody(unittest.TestCase):
    def test_comment_shaped_lines_inside_a_multi_line_verbatim_string_are_a_prose_block(self):
        text = 'var sql = @"select 1\n// one\n// two\n";\nint x;\n'
        self.assertEqual(found("a.cs", text), [("C1", 2)])



class TestAgentContextFalsePositivesInCpython(unittest.TestCase):
    """Two CPython comments that the agent-context pack flags, pinned because that pack is opt-in."""

    AGENT_CONTEXT = governance.matcher(("agent-context",))

    def test_as_requested_in_a_cpython_comment_is_a_governance_reference(self):
        # The pins hold because the core never flags these, and only the opt-in pack does.
        text = "# which is calling CloseHandle as requested in [1], so there is nothing\n"
        self.assertEqual(engine.check_text("a.py", text, self.AGENT_CONTEXT).findings[0].message,
                         "governance reference 'as requested'")

    def test_per_the_spec_in_a_cpython_comment_is_a_governance_reference(self):
        text = "# Map conditions (per the spec) to signals\n"
        self.assertEqual(engine.check_text("a.py", text, self.AGENT_CONTEXT).findings[0].message,
                         "governance reference 'per the spec'")


class TestRubyLiteralsTheLineScannerDoesNotKnow(unittest.TestCase):
    def test_a_character_literal_of_a_hash_reads_a_comment(self):
        # The line scanner does not know Ruby's `?#` character literal.
        self.assertEqual(found("a.rb", "x = ?#docs/prefix\n"), [("C3", 1)])

    def test_a_percent_word_list_with_a_hash_reads_a_comment(self):
        # The line scanner does not know Ruby's percent literals.
        self.assertEqual(found("a.rb", "%w[a #docs/prefix]\n"), [("C3", 1)])

    def test_a_regex_literal_with_a_hash_reads_a_comment(self):
        # The line scanner does not know Ruby's regex literals.
        self.assertEqual(found("a.rb", "/#docs/prefix/ =~ s\n"), [("C3", 1)])

    def test_an_interpolation_inside_a_percent_regex_reads_a_comment(self):
        # The line scanner does not know `%r{}`, so the `#` that opens an interpolation starts a comment.
        self.assertEqual(comments("a.rb", "X = %r{a#{B}c}\n"), [["#{B}c}"]])

    def test_a_second_heredoc_on_one_line_is_not_tracked(self):
        # Only the first heredoc opened on a line is tracked, so the second payload reads as code.
        self.assertEqual(found("a.rb", "foo(<<~A, <<~B)\na\nA\n# see ADR-7\nB\n"), [("C3", 4)])

    def test_a_backtick_heredoc_payload_reads_comments(self):
        # The opener pattern knows quoted identifiers but not backtick ones.
        self.assertEqual(found("a.rb", "x = <<~`X`\n# see ADR-7\nX\n"), [("C3", 2)])

    def test_a_shift_with_a_bare_word_reads_as_a_heredoc_opener(self):
        # `a <<b` is an append, but a space before `<<` and a word after it is the shape of an opener.
        with self.assertRaises(LexError):
            engine.check_text("a.rb", "puts x if a <<b\n")

    def test_a_heredoc_marker_in_a_regex_character_class_is_an_opener(self):
        # The line scanner does not know regex literals, so `[<<a` in one is the shape of an opener.
        with self.assertRaises(LexError):
            engine.check_text("a.rb", "x =~ /[<<a]/\n")

    def test_an_end_marker_inside_a_multi_line_string_ends_the_source(self):
        # The line scanner cannot see a string that spans lines, so a line of `__END__` in one ends the source.
        self.assertEqual(found("a.rb", 'x = "a\n__END__\nb"\n# see ADR-7\n'), [])

    def test_a_heredoc_after_a_binary_sign_is_not_followed(self):
        # A sign right after a word is read as binary, and `<<` after it as an append, so the payload reads as code.
        self.assertEqual(found("a.rb", "x = a+<<EOS\n# see ADR-7\nEOS\n"), [("C3", 2)])


class TestMakefileShapesTheLexerDoesNotKnow(unittest.TestCase):
    def test_the_text_after_a_semicolon_on_a_rule_line_reads_make_syntax(self):
        # The recipe after `;` is not told from make syntax, so quotes do not protect the hash.
        self.assertEqual(found("Makefile", 'all: ; echo "# ADR-9"\n'), [("C3", 1)])

    def test_a_custom_recipe_prefix_is_not_a_recipe(self):
        # `.RECIPEPREFIX` is not read, so a recipe line behind it is make syntax.
        self.assertEqual(found("Makefile", '.RECIPEPREFIX = >\nall:\n> echo "# ADR-9"\n'), [("C3", 3)])

    def test_a_comment_line_inside_a_define_block_is_not_read(self):
        # The body of a `define` is content, so a comment written in it is never judged.
        self.assertEqual(found("Makefile", "define rule\n# see ADR-7\nendef\n"), [])


class TestGoCgoPreamble(unittest.TestCase):
    def test_c_code_in_the_comment_before_the_c_import_is_a_prose_block(self):
        # The preamble is C source for cgo, but to Go it is a comment, so its lines read as prose.
        text = 'package a\n\n// #include <stdlib.h>\n// static int twice(int x) { return 2 * x; }\nimport "C"\n'
        self.assertEqual(found("a.go", text), [("C1", 3)])


class TestGoDirectiveReasons(unittest.TestCase):
    def test_the_reason_of_a_lint_ignore_directive_is_never_judged(self):
        # There is no second `//`, so the reason is part of the directive.
        self.assertEqual(found("a.go", "//lint:ignore SA1019 see ADR-9\nx := 1\n"), [])


class TestJavaUnicodeEscapes(unittest.TestCase):
    def test_a_unicode_newline_escape_in_a_line_comment_is_not_a_line_end(self):
        # javac translates the escape before lexing, so the code after it is code; here it reads as comment text.
        text = "int a; // end \\u000a see ADR-9\n"
        self.assertEqual(found("A.java", text), [("C3", 1)])


class TestSqlShapesOtherDialectsReadDifferently(unittest.TestCase):
    def test_a_postgres_xor_written_with_spaces_reads_a_comment(self):
        # Outside MySQL mode a `#` before a space opens a comment, so the right-hand side of the XOR is comment text.
        self.assertEqual(comments("a.sql", "SELECT a # b FROM t;\n"), [["# b FROM t;"]])

    def test_a_nested_block_comment_ends_at_its_first_close(self):
        # Postgres and T-SQL nest block comments, but here the first `*/` ends one, so the rest reads as code.
        self.assertEqual(comments("a.sql", "/* a /* b */ c */\n"), [["/* a /* b */"]])

    def test_a_dash_pair_in_a_bracketed_name_reads_a_comment(self):
        # A T-SQL `[...]` name is read as code, so a `--` inside one opens a comment.
        self.assertEqual(comments("a.sql", "SELECT [a--b] FROM t;\n"), [["--b] FROM t;"]])

    def test_a_dash_pair_in_a_dollar_quoted_string_reads_a_comment(self):
        # A dollar-quoted body is lexed as SQL whenever it can be, also when it is a plain string literal.
        self.assertEqual(found("a.sql", "SELECT $$ -- see ADR-9 $$;\n"), [("C3", 1)])

    def test_a_quote_in_a_bracketed_name_opens_a_string(self):
        # A T-SQL `[...]` name is read as code, so a `'` inside one opens a string that may never close.
        with self.assertRaises(LexError):
            engine.check_text("a.sql", "SELECT [it's] FROM t;\nGO\n")

    def test_a_backslash_before_a_quote_escapes_it_in_a_sqlite_file_with_backtick_names(self):
        # Backtick names make the file MySQL, where `\'` escapes a quote, but SQLite reads `'C:\'` as a whole string.
        with self.assertRaises(LexError):
            engine.check_text("a.sql", "CREATE TABLE `t`(p TEXT DEFAULT 'C:\\');\n-- see ADR-9\n")

    def test_a_mysql_file_with_no_marker_and_two_escaped_quotes_reads_as_standard_sql(self):
        # Read the standard way, each `\'` ends its string, so the text between the two escapes is one string.
        text = "INSERT INTO t VALUES ('O\\'Brien');\n-- see ADR-9\nINSERT INTO t VALUES ('D\\'Arcy');\n"
        self.assertEqual(found("a.sql", text), [])

    def test_a_close_inside_a_string_in_an_executable_comment_ends_the_comment(self):
        # An executable comment ends at its first `*/`, so the quote after it opens a string that never closes.
        with self.assertRaises(LexError):
            engine.check_text("a.sql", "/*!40101 SET @a = '*/' */;\n")

    def test_an_oracle_q_quote_is_read_as_a_plain_string(self):
        # Oracle `q'[...]'` is not known, so the `'` inside its brackets ends the string and the last one never closes.
        with self.assertRaises(LexError):
            engine.check_text("a.sql", "SELECT q'[it's]' FROM dual;\n")

    def test_a_temporary_procedure_called_without_exec_at_the_start_of_a_file_switches_to_mysql(self):
        # A `#` that starts a statement marks MySQL, where every later `#t` opens a comment.
        text = "#load_rows\nGO\nINSERT INTO #t VALUES ('C:\\'); -- see ADR-9\nGO\n"
        self.assertEqual(comments("a.sql", text), [["#load_rows"], [], ["#t VALUES ('C:\\'); -- see ADR-9"], []])

    def test_a_delimiter_after_code_or_a_comment_on_its_line_does_not_switch(self):
        # A `DELIMITER` command switches only at the start of a line, so `$$` here opens dollar quotes.
        procedures = "CREATE PROCEDURE a() BEGIN SELECT 1; END $$\nCREATE PROCEDURE b() BEGIN SELECT 2; END $$\n"
        for first in ("/* setup */ DELIMITER $$\n", "SET x = 1; DELIMITER $$\n"):
            with self.assertRaises(LexError) as caught:
                engine.check_text("a.sql", first + procedures + "DELIMITER ;\n")
            self.assertEqual((caught.exception.line, caught.exception.message), (3, "unterminated dollar quote"))
