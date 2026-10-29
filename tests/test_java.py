"""Java lexing: text blocks and characters are content, and Javadoc tags do not count as prose."""
import os
import re
import unittest

from agent_comment_lint.lexers import LexError, family_for
from support import comments, found

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT_BLOCK = '"' * 3


class TestScope(unittest.TestCase):
    def test_the_java_extension_is_covered(self):
        self.assertEqual(family_for("src/A.java").name, "java")
        self.assertEqual(found("A.java", "// see ADR-9\n"), [("C3", 1)])

    def test_the_pre_commit_filter_matches_java_files(self):
        with open(os.path.join(REPO, ".pre-commit-hooks.yaml"), encoding="utf-8") as handle:
            filters = re.findall(r"^\s*files: (.+)$", handle.read(), flags=re.M)
        self.assertEqual(len(filters), 2)
        self.assertEqual(filters[0], filters[1])
        self.assertTrue(re.search(filters[0], "src/A.java"))
        self.assertFalse(re.search(filters[0], "A.javascript"))


class TestTextBlocks(unittest.TestCase):
    def test_a_text_block_is_content(self):
        self.assertEqual(found("A.java", 'String s = """\n// ADR-9\n""";\n'), [])

    def test_an_unterminated_text_block_cannot_be_lexed(self):
        with self.assertRaises(LexError):
            family_for("A.java").lex('String s = """\nx\n')

    def test_an_escaped_quote_run_does_not_close_a_text_block(self):
        text = 'String s = """\n  a \\"""\n// ADR-9\n  """;\n'
        self.assertEqual(found("A.java", text), [])

    def test_a_comment_after_a_text_block_that_opens_and_closes_is_read(self):
        text = 'String s = """\n  x\n  """; int a = 1;\nint b = 2; // see ADR-9\n'
        self.assertEqual(found("A.java", text), [("C3", 4)])

    def test_triple_quotes_in_a_line_comment_open_nothing(self):
        self.assertEqual(found("A.java", '// ' + TEXT_BLOCK + '\nint a; // see ADR-9\n'), [("C3", 2)])

    def test_triple_quotes_in_a_char_literal_or_string_open_nothing(self):
        text = 'char c = \'"\'; String s = "\\"\\"\\""; String t = "";\nint a; // see ADR-9\n'
        self.assertEqual(found("A.java", text), [("C3", 2)])

    def test_a_text_block_holding_comment_delimiters_is_content(self):
        text = 'String s = """\n  /* x */ /*\n""";\nint a; // see ADR-9\n'
        self.assertEqual(found("A.java", text), [("C3", 4)])


class TestJavadoc(unittest.TestCase):
    def test_javadoc_tags_do_not_count_as_prose(self):
        self.assertEqual(found("A.java", "/**\n * Adds.\n * @param a left\n * @param b right\n */\n"), [])

    def test_two_prose_lines_in_javadoc_are_a_block(self):
        self.assertEqual([rule for rule, _ in found("A.java", "/**\n * Adds.\n * Also.\n */\n")], ["C1"])

    def test_one_prose_line_with_return_and_throws_tags_is_clean(self):
        text = "/**\n * Adds.\n * @return the sum\n * @throws IllegalStateException when full\n */\n"
        self.assertEqual(found("A.java", text), [])

    def test_code_and_pre_content_in_javadoc_is_prose(self):
        text = "/**\n * Adds {@code a}.\n * <pre>\n * add(1, 2)\n * </pre>\n */\n"
        self.assertEqual([rule for rule, _ in found("A.java", text)], ["C1"])


class TestLiterals(unittest.TestCase):
    def test_an_annotation_string_is_content(self):
        self.assertEqual(found("A.java", '@SuppressWarnings("unchecked // see ADR-9")\n'), [])

    def test_a_char_literal_holding_a_quote_or_slash_is_content(self):
        text = "char a = '\"'; char b = '\\''; char c = '/';\nint d; // see ADR-9\n"
        self.assertEqual(found("A.java", text), [("C3", 2)])

    def test_string_literals_holding_comment_openers_are_content(self):
        text = 'String a = "/*"; String b = "//"; String c = "\\"";\nint d; // see ADR-9\n'
        self.assertEqual(found("A.java", text), [("C3", 2)])

    def test_a_lambda_division_before_a_comment_is_read(self):
        self.assertEqual(found("A.java", "f = x -> x / 2; // see ADR-9\n"), [("C3", 1)])

    def test_generics_are_code(self):
        self.assertEqual(found("A.java", "List<Map<String, int[]>> a; // see ADR-9\n"), [("C3", 1)])

    def test_empty_and_one_line_doc_comments_lex(self):
        self.assertEqual(comments("A.java", "/**/ int a;\n/** */ int b;\n"), [["/**/"], ["/** */"]])


class TestLineEndings(unittest.TestCase):
    def test_crlf_behaves_like_lf(self):
        text = '/**\n * Adds.\n * @return x\n */\nString s = """\n// ADR-9\n""";\nint a; // see ADR-9\n'
        self.assertEqual(found("A.java", text.replace("\n", "\r\n")), found("A.java", text))
        self.assertEqual(found("A.java", text), [("C3", 8)])


if __name__ == "__main__":
    unittest.main()
