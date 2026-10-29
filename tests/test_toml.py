"""TOML lexing: `#` comments, with multi-line strings as content."""
import unittest

from agent_comment_lint.lexers import LexError, family_for
from support import comments, found


class TestScope(unittest.TestCase):
    def test_toml_is_covered(self):
        self.assertEqual(family_for("pyproject.toml").name, "toml")


class TestComments(unittest.TestCase):
    def test_a_two_line_comment_is_one_block(self):
        self.assertEqual(found("a.toml", "# one\n# two\na = 1\n"), [("C1", 1)])

    def test_a_hash_in_a_string_is_not_a_comment(self):
        self.assertEqual(found("a.toml", 'a = "x # ADR-9"\n'), [])

    def test_a_hash_in_a_literal_string_is_not_a_comment(self):
        self.assertEqual(found("a.toml", "a = 'x # ADR-9'\n"), [])

    def test_a_backslash_does_not_escape_in_a_literal_string(self):
        self.assertEqual(found("a.toml", "a = 'C:\\path' # see ADR-9\n"), [("C3", 1)])

    def test_an_escaped_quote_stays_inside_a_basic_string(self):
        self.assertEqual(found("a.toml", 'a = "x\\" # ADR-9"\n'), [])

    def test_a_trailing_comment_is_reported(self):
        self.assertEqual(found("a.toml", "a = 1 # see ADR-9\n"), [("C3", 1)])


class TestMultiLineStrings(unittest.TestCase):
    def test_a_multi_line_string_is_content(self):
        self.assertEqual(found("a.toml", 'a = """\n# ADR-9\n"""\n'), [])

    def test_a_multi_line_literal_string_is_content(self):
        self.assertEqual(found("a.toml", "a = '''\n# ADR-9\n'''\n"), [])

    def test_a_comment_after_a_closing_triple_quote_is_read(self):
        self.assertEqual(found("a.toml", "a = '''\nx\n''' # see ADR-9\n"), [("C3", 3)])

    def test_a_string_that_opens_and_closes_on_one_line(self):
        self.assertEqual(found("a.toml", 'a = """x""" # see ADR-9\n'), [("C3", 1)])

    def test_extra_quotes_before_the_closer_belong_to_the_string(self):
        self.assertEqual(found("a.toml", 'a = """"x""""" # see ADR-9\n'), [("C3", 1)])
        self.assertEqual(found("a.toml", 'a = """\nx""""" # see ADR-9\n'), [("C3", 2)])

    def test_an_escaped_quote_does_not_close_a_multi_line_basic_string(self):
        self.assertEqual(found("a.toml", 'a = """\nx\\""" # ADR-9\n"""\n'), [])

    def test_a_backslash_does_not_escape_in_a_multi_line_literal(self):
        self.assertEqual(found("a.toml", "a = '''\nx\\''' # see ADR-9\n"), [("C3", 2)])

    def test_a_comment_before_the_opener_is_read(self):
        self.assertEqual(found("a.toml", 'a = 1 # see ADR-9 """\nb = 2\n'), [("C3", 1)])

    def test_the_closing_line_reads_as_string_then_code(self):
        self.assertEqual(comments("a.toml", "a = '''\nx''' # c\n"), [[], ["# c"]])

    def test_an_unterminated_multi_line_string_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found("a.toml", 'a = """\nx\n')
        self.assertEqual(caught.exception.line, 1)


if __name__ == "__main__":
    unittest.main()
