"""Makefile lexing: make syntax outside recipes, shell rules inside them, define blocks as content."""
import os
import re
import unittest

from agent_comment_lint.lexers import LexError, family_for
from support import LONG, comments, found

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

    def test_a_continued_comment_is_one_block(self):
        self.assertEqual(found("Makefile", "# first prose line \\\n  second prose line\n"), [("C1", 1)])

    def test_a_continued_trailing_comment_is_one_block(self):
        self.assertEqual(found("Makefile", "x = 1 # first prose \\\n  second prose\nall:\n"), [("C1", 1)])

    def test_a_blank_line_after_a_continued_comment_ends_its_block(self):
        self.assertEqual(found("Makefile", "# a \\\n\n# b\n"), [])

    def test_a_long_continuation_of_a_comment_is_reported(self):
        self.assertEqual(found("Makefile", "# one \\\n" + LONG + "\n"), [("C1", 1), ("C7", 2)])

    def test_a_continued_line_inside_a_reference_is_not_a_comment_line(self):
        self.assertEqual(found("Makefile", "X = $(shell echo \\\n# one prose \\\n# two prose)\n"), [])

    def test_a_shebang_is_not_prose(self):
        self.assertEqual(found("Makefile", "#!/usr/bin/make -f\n# one line\nall:\n"), [])


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

    def test_a_continued_line_inside_a_recipe_reference_is_not_a_comment_line(self):
        self.assertEqual(found("Makefile", "all:\n\techo $(shell echo \\\n# one prose \\\n# two prose)\n"), [])

    def test_a_hash_a_continuation_carries_into_a_word_is_not_a_comment_line(self):
        self.assertEqual(found("Makefile", "all:\n\techo a\\\n#one prose\n# two prose\n"), [])


class TestRuleContext(unittest.TestCase):
    def test_a_tab_line_before_any_rule_is_make_syntax(self):
        self.assertEqual(found("Makefile", 'x = 1\n\techo "# see ADR-9"\n'), [("C3", 2)])

    def test_an_assignment_closes_the_rule(self):
        text = "all:\n\techo hi\nX = 1\n\tY := don't\n"
        self.assertEqual(found("Makefile", text), [])

    def test_a_tab_line_in_a_conditional_outside_a_rule_is_make_syntax(self):
        self.assertEqual(found("Makefile", 'ifeq ($(OS),x)\n\tMSG := "see # docs/x"\nendif\n'), [("C3", 2)])

    def test_a_recipe_after_a_conditional_inside_a_rule_is_still_a_recipe(self):
        text = 'all:\nifeq ($(A),b)\n\techo "# ADR-9"\nelse\n\techo "# ADR-9"\nendif\n\techo "# ADR-9"\n'
        self.assertEqual(found("Makefile", text), [])

    def test_an_indented_conditional_keeps_the_rule_open(self):
        text = 'all:\n  ifdef A\n\techo "# ADR-9"\n  endif # A\n\techo "# ADR-9"\n'
        self.assertEqual(found("Makefile", text), [])

    def test_blank_and_comment_lines_keep_the_rule_open(self):
        self.assertEqual(found("Makefile", 'all:\n\n# note\n\techo "# ADR-9"\n'), [])

    def test_a_double_colon_rule_opens_a_rule(self):
        self.assertEqual(found("Makefile", 'all::\n\techo "# ADR-9"\n'), [])

    def test_a_rule_line_with_references_opens_a_rule(self):
        self.assertEqual(found("Makefile", '$(OBJS): %.o: %.c $(X:a=b)\n\techo "# ADR-9"\n'), [])

    def test_an_assignment_operator_before_the_colon_is_not_a_rule(self):
        for head in ("X := a", "X ::= a", "X :::= a", "X ?= a:b", "X += a:b", "X != echo a:b", "X = a:b"):
            self.assertEqual(found("Makefile", head + '\n\techo "# see ADR-9"\n'), [("C3", 2)], head)

    def test_a_colon_inside_a_reference_opens_no_rule(self):
        self.assertEqual(found("Makefile", '$(eval $(call T,a:b))\n\techo "# see ADR-9"\n'), [("C3", 2)])

    def test_a_target_specific_variable_closes_the_rule(self):
        for head in ("all: X = 1", "all: X := 1", "%.o: CFLAGS += -O2", "all:: X = 1"):
            self.assertEqual(found("Makefile", 'all:\n' + head + '\n\techo "# see ADR-9"\n'), [("C3", 3)], head)

    def test_an_assignment_after_a_semicolon_is_part_of_the_recipe(self):
        self.assertEqual(found("Makefile", 'all: ; X=1\n\techo "# ADR-9"\n'), [])

    def test_a_directive_closes_the_rule(self):
        for line in ("include a.mk", "-include a.mk", "sinclude a.mk", "export X", "unexport X", "override X = 1",
                     "vpath %.c src", "export a: b", "define X\nendef"):
            self.assertEqual(found("Makefile", 'all:\n' + line + '\n\techo "# see ADR-9"\n')[-1:],
                             [("C3", 3 + line.count("\n"))], line)

    def test_a_conditional_keyword_used_as_a_variable_closes_the_rule(self):
        self.assertEqual(found("Makefile", 'all:\nelse = 1\n\techo "# see ADR-9"\n'), [("C3", 3)])

    def test_a_rule_line_opens_a_new_rule(self):
        self.assertEqual(found("Makefile", 'X = 1\nall: X\n\techo "# ADR-9"\n'), [])


class TestRecipePrefixes(unittest.TestCase):
    def test_a_comment_behind_a_prefix_is_read(self):
        for prefix in ("@", "-", "+", "@-", "@ ", " @\t-+"):
            self.assertEqual(found("Makefile", "all:\n\t" + prefix + "# see ADR-9\n"), [("C3", 2)], prefix)

    def test_prefixed_comment_lines_are_one_block(self):
        self.assertEqual(found("Makefile", "all:\n\t@# one\n\t@# two\n"), [("C1", 2)])

    def test_a_run_of_plain_and_prefixed_comment_lines_is_one_block(self):
        self.assertEqual(found("Makefile", "all:\n\t# one\n\t@# two\n\t-# three\n"), [("C1", 2)])

    def test_a_prefixed_comment_line_after_code_starts_a_block(self):
        self.assertEqual(found("Makefile", "all:\n\t@echo hi\n\t@# one\n\techo bye\n"), [])

    def test_a_long_prefixed_comment_line_is_reported(self):
        self.assertEqual(found("Makefile", "all:\n\t@# " + LONG + "\n"), [("C7", 2)])

    def test_the_prefix_is_read_only_at_the_start_of_a_recipe_line(self):
        self.assertEqual(found("Makefile", "all:\n\techo a \\\n@# see ADR-9\n"), [])


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

    def test_only_a_bare_define_nests(self):
        self.assertEqual(found("Makefile", "define X\noverride define Y\nendef\nall:\n"), [])

    def test_a_tab_line_in_a_define_body_is_content(self):
        self.assertEqual(found("Makefile", "define X\n\tendef\n# see ADR-9\nendef\n"), [])
        self.assertEqual(found("Makefile", "define X\n\tdefine y\nendef\n"), [])

    def test_a_define_closes_the_rule(self):
        self.assertEqual(found("Makefile", 'all:\ndefine X\nx\nendef\n\techo "# see ADR-9"\n'), [("C3", 5)])


class TestAssignmentsAndLineEndings(unittest.TestCase):
    def test_an_assignment_to_a_variable_named_define_opens_no_block(self):
        for head in ("define = 1", "define := 1", "define ?= x", "define += x", "define != x", "override define = 1"):
            self.assertEqual(found("Makefile", head + "\n"), [], head)

    def test_a_define_named_with_an_assignment_operator_is_still_a_block(self):
        self.assertEqual(found("Makefile", "define NAME =\n# ADR-9\nendef\n"), [])

    def test_a_hash_right_after_a_reference_in_a_recipe_is_not_a_comment(self):
        self.assertEqual(found("Makefile", "all:\n\tcurl $(URL)#docs/frag\n"), [])

    def test_a_hash_after_a_reference_and_a_space_in_a_recipe_is_a_comment(self):
        self.assertEqual(found("Makefile", "all:\n\techo $(X) # see ADR-9\n"), [("C3", 2)])

    def test_crlf_line_endings_read_like_lf(self):
        self.assertEqual(found("Makefile", "x = a # see ADR-9\r\n"), [("C3", 1)])
        self.assertEqual(found("Makefile", 'all:\r\n\techo "# ADR-9"\r\n\techo a # see ADR-9\r\n'), [("C3", 3)])
        self.assertEqual(found("Makefile", "define X\r\n# ADR-9\r\nendef # see ADR-9\r\n"), [("C3", 3)])

    def test_an_exported_assignment_with_a_trailing_comment_is_read(self):
        self.assertEqual(found("Makefile", "export X = 1 # see ADR-9\n"), [("C3", 1)])

    def test_an_assignment_to_define_with_wide_spacing_opens_no_block(self):
        for head in ("define  = 1", "define\t = 1", "define \t:=  1"):
            self.assertEqual(found("Makefile", head + "\n"), [], repr(head))
