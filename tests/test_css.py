"""Stylesheet lexing: `/* */` is the only comment, and a quoted string is content."""
import unittest

from agent_comment_lint.lexers import LexError, family_for
from support import LONG, comments, found


class TestCss(unittest.TestCase):
    def test_stylesheets_are_covered(self):
        self.assertEqual(family_for("src/styles/tokens.css").name, "css")

    def test_a_wrapped_block_comment_is_reported(self):
        self.assertEqual(found("a.css", "/*\n * one\n * two\n */\na { color: red; }\n"), [("C1", 2)])

    def test_a_block_opened_after_a_rule_is_scored_from_its_opening_line(self):
        self.assertEqual(found("a.css", "a { color: red; } /* one\n   two */\nb { color: blue; }\n"), [("C1", 1)])

    def test_an_unterminated_block_comment_is_refused_with_its_opening_line(self):
        with self.assertRaises(LexError) as caught:
            found("a.css", "a { color: red; }\nb { color: blue; } /* never closes\n")
        self.assertEqual((caught.exception.line, caught.exception.message), (2, "unterminated block comment"))

    def test_a_governance_reference_in_a_comment_is_reported(self):
        self.assertEqual(found("a.css", "a { color: red; } /* see ADR-0001 */\n"), [("C3", 1)])

    def test_an_overlong_comment_line_is_reported(self):
        self.assertEqual(found("a.css", "/* %s */\n" % LONG), [("C7", 1)])

    def test_a_double_slash_is_not_a_comment(self):
        text = "a { background: url(http://host/ADR-0001.png); }\n// one\n// two\n"
        self.assertEqual(found("a.css", text), [])

    def test_a_comment_opener_inside_a_string_is_content(self):
        text = "a::before { content: \"/* ADR-0001\"; }\nb { color: red; }\n"
        self.assertEqual(comments("a.css", text), [[], []])

    def test_a_comment_after_a_string_is_still_reported(self):
        self.assertEqual(found("a.css", "a { content: '/*'; } /* see ADR-0001 */\n"), [("C3", 1)])

    def test_universal_selector_lines_are_not_prose(self):
        self.assertEqual(found("a.css", "*,\n*::before,\n*::after {\n  margin: 0;\n}\n"), [])

    def test_an_unterminated_string_is_refused_with_its_line(self):
        with self.assertRaises(LexError) as caught:
            found("a.css", "a { color: red; }\nb { content: \"never closes; }\n")
        self.assertEqual((caught.exception.line, caught.exception.message), (2, "unterminated string"))

    def test_an_escaped_quote_does_not_end_the_string(self):
        self.assertEqual(found("a.css", 'a { content: "\\" /* ADR-0001 */"; }\n'), [])
