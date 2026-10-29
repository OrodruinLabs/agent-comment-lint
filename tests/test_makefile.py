"""Makefile lexing: make syntax outside recipes, shell rules inside them, define blocks as content."""
import os
import re
import unittest

from agent_comment_lint.lexers import LexError, family_for
from support import comments, found

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestScope(unittest.TestCase):
    def test_the_conventional_names_and_the_extension_are_covered(self):
        for path in ("Makefile", "makefile", "GNUmakefile", "build/Makefile", "rules.mk"):
            self.assertEqual(found(path, "# ADR-9\n"), [("C3", 1)], path)

    def test_a_name_that_only_ends_in_makefile_is_not_covered(self):
        self.assertIsNone(family_for("MyMakefile"))
        self.assertIsNone(family_for("Makefile.bak"))

    def test_the_pre_commit_filter_matches_the_makefile_names_and_extension(self):
        with open(os.path.join(REPO, ".pre-commit-hooks.yaml"), encoding="utf-8") as handle:
            filters = re.findall(r"^\s*files: (.+)$", handle.read(), flags=re.M)
        self.assertEqual(len(filters), 2)
        self.assertEqual(filters[0], filters[1])
        covered = re.compile(filters[0])
        for path in ("Makefile", "dir/makefile", "dir/GNUmakefile", "dir/rules.mk"):
            self.assertTrue(covered.search(path), path)
        for path in ("dir/MyMakefile", "dir/Makefile.bak"):
            self.assertFalse(covered.search(path), path)


class TestOutsideRecipes(unittest.TestCase):
    def test_a_trailing_comment_is_read(self):
        self.assertEqual(found("Makefile", "x = a # see ADR-9\n"), [("C3", 1)])

    def test_an_escaped_hash_is_not_a_comment(self):
        self.assertEqual(found("Makefile", "x = a \\# ADR-9\n"), [])

    def test_a_hash_after_an_escaped_backslash_is_a_comment(self):
        self.assertEqual(found("Makefile", "x = a \\\\# ADR-9\n"), [("C3", 1)])

    def test_a_two_line_comment_is_one_block(self):
        self.assertEqual(found("Makefile", "# one\n# two\nall:\n"), [("C1", 1)])

    def test_a_hash_in_the_middle_of_a_word_starts_a_comment(self):
        self.assertEqual(comments("Makefile", "x = a#b\n"), [["#b"]])

    def test_quotes_do_not_protect_a_hash(self):
        self.assertEqual(found("Makefile", 'x = "a # ADR-9"\n'), [("C3", 1)])

    def test_a_hash_in_a_reference_is_content(self):
        self.assertEqual(found("Makefile", "x = $(shell echo # ADR-9)\n"), [])
        self.assertEqual(found("Makefile", "x = ${y#docs/}\n"), [])

    def test_a_hash_in_a_nested_reference_is_content(self):
        self.assertEqual(comments("Makefile", "x = $(a $(b #) #) # c\n"), [["# c"]])

    def test_a_doubled_dollar_opens_no_reference(self):
        self.assertEqual(found("Makefile", "x = $$(# ADR-9\n"), [("C3", 1)])

    def test_a_reference_may_span_a_continued_line(self):
        self.assertEqual(found("Makefile", "x = $(foo \\\n  # ADR-9)\n"), [])

    def test_an_unterminated_reference_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found("Makefile", "x = 1\ny = $(foo\nz = 2\n")
        self.assertEqual(caught.exception.line, 2)

    def test_a_comment_ending_in_a_backslash_continues_onto_the_next_line(self):
        self.assertEqual(comments("Makefile", "# one \\\ntwo see ADR-9\nall:\n"),
                         [["# one \\"], ["two see ADR-9"], []])

    def test_a_continued_comment_opens_the_next_line_in_a_comment(self):
        lines = family_for("Makefile").lex("# one \\\ntwo\nall:\n")
        self.assertEqual([line.opens_in for line in lines], ["code", "comment", "code"])


class TestRecipes(unittest.TestCase):
    def test_a_hash_in_a_quoted_recipe_string_is_not_a_comment(self):
        self.assertEqual(found("Makefile", 'all:\n\techo "# ADR-9"\n'), [])
        self.assertEqual(found("Makefile", "all:\n\techo '# ADR-9'\n"), [])

    def test_a_hash_that_starts_a_shell_word_is_a_comment(self):
        self.assertEqual(found("Makefile", "all:\n\techo hi # ADR-9\n"), [("C3", 2)])

    def test_a_hash_inside_a_word_is_not_a_comment(self):
        self.assertEqual(found("Makefile", "all:\n\tcurl http://x/#docs/frag\n"), [])

    def test_a_hash_in_a_make_reference_is_content(self):
        self.assertEqual(found("Makefile", "all:\n\techo $(A#docs/) ${B#docs/}\n"), [])

    def test_a_doubled_dollar_is_a_literal_dollar(self):
        self.assertEqual(found("Makefile", "all:\n\techo $$#docs/x\n"), [])

    def test_a_tab_line_is_a_recipe_wherever_it_stands(self):
        self.assertEqual(found("Makefile", 'x = 1\n\techo "# ADR-9"\n'), [])

    def test_a_continued_recipe_line_carries_the_quote_over(self):
        self.assertEqual(found("Makefile", 'all:\n\techo "a \\\n# ADR-9"\n'), [])

    def test_a_continued_recipe_line_needs_no_tab(self):
        self.assertEqual(found("Makefile", "all:\n\techo a \\\n  b # ADR-9\n"), [("C3", 3)])

    def test_an_unclosed_quote_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found("Makefile", 'all:\n\techo "a\n')
        self.assertEqual(caught.exception.line, 2)

    def test_a_recipe_heredoc_opens_nothing(self):
        self.assertEqual(found("Makefile", "all:\n\tcat <<EOF\n\t# ADR-9\n"), [("C3", 3)])


class TestDefine(unittest.TestCase):
    def test_a_define_block_is_content(self):
        self.assertEqual(found("Makefile", "define X\n# ADR-9\nendef\n"), [])

    def test_a_define_block_opens_its_lines_in_a_string(self):
        lines = family_for("Makefile").lex("define X\n# a\nendef\nall:\n")
        self.assertEqual([line.opens_in for line in lines], ["code", "string", "string", "code"])

    def test_the_define_modifiers_are_read(self):
        for head in ("override define X", "export define X", "private define X", "  override export define X"):
            self.assertEqual(found("Makefile", head + "\n# ADR-9\nendef\n"), [], head)

    def test_a_nested_define_is_counted(self):
        self.assertEqual(found("Makefile", "define A\ndefine B\nendef\n# ADR-9\nendef\n# see ADR-9\n"), [("C3", 6)])

    def test_endef_may_be_indented_and_carry_a_comment(self):
        self.assertEqual(found("Makefile", "define X\nx\n  endef # see ADR-9\n"), [("C3", 3)])

    def test_the_define_line_is_a_make_line(self):
        self.assertEqual(found("Makefile", "define X # see ADR-9\nx\nendef\n"), [("C3", 1)])

    def test_an_unterminated_define_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found("Makefile", "x = 1\ndefine X\nx\n")
        self.assertEqual(caught.exception.line, 2)

    def test_an_unterminated_nested_define_cannot_be_lexed(self):
        with self.assertRaises(LexError):
            found("Makefile", "define A\ndefine B\nendef\n")

    def test_define_in_a_recipe_opens_nothing(self):
        self.assertEqual(found("Makefile", "all:\n\tdefine X\n"), [])
