"""Go lexing: raw strings and runes are content, and a directive such as `//go:build` is not comment prose."""
import os
import re
import unittest

from agent_comment_lint.lexers import LexError, family_for
from support import LONG, comments, found

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestScope(unittest.TestCase):
    def test_the_go_extension_is_covered(self):
        self.assertEqual(family_for("cmd/main.go").name, "go")
        self.assertEqual(found("cmd/main.go", "// see ADR-9\n"), [("C3", 1)])

    def test_the_pre_commit_filter_matches_go_files(self):
        with open(os.path.join(REPO, ".pre-commit-hooks.yaml"), encoding="utf-8") as handle:
            filters = re.findall(r"^\s*files: (.+)$", handle.read(), flags=re.M)
        self.assertEqual(len(filters), 2)
        self.assertEqual(filters[0], filters[1])
        self.assertTrue(re.search(filters[0], "cmd/main.go"))
        self.assertFalse(re.search(filters[0], "go.mod"))


class TestLiterals(unittest.TestCase):
    def test_a_raw_string_across_lines_is_content(self):
        self.assertEqual(found("a.go", "var s = `\n// ADR-9\n`\n"), [])

    def test_a_rune_holding_a_slash_is_not_a_comment(self):
        self.assertEqual(comments("a.go", "r := '/'\n"), [[]])

    def test_a_rune_holding_a_backtick_opens_no_raw_string(self):
        self.assertEqual(found("a.go", "r := '`' // see ADR-9\n"), [("C3", 1)])

    def test_an_unterminated_raw_string_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found("a.go", "var s = `x\n")
        self.assertEqual(caught.exception.line, 1)

    def test_an_unterminated_interpreted_string_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found("a.go", 'package a\nvar s = "x\n// see ADR-9\n')
        self.assertEqual(caught.exception.line, 2)

    def test_quote_runes_are_content(self):
        text = "a, b := '\"', \"'\" // see ADR-9\n"
        self.assertEqual(comments("a.go", text), [["// see ADR-9"]])

    def test_a_raw_string_holding_a_block_close_is_content(self):
        self.assertEqual(found("a.go", "/* one */ var s = `*/` // see ADR-9\n"), [("C3", 1)])

    def test_comment_shaped_lines_inside_a_raw_string_are_not_a_prose_block(self):
        self.assertEqual(found("a.go", "var s = `\n// one\n/* two\n`\n// see ADR-9\n"), [("C3", 5)])


class TestComments(unittest.TestCase):
    def test_a_two_line_doc_comment_is_one_block(self):
        self.assertEqual(found("a.go", "// Foo does x.\n// It also y.\nfunc Foo() {}\n"), [("C1", 1)])

    def test_a_multi_line_block_comment_is_one_block(self):
        self.assertEqual(found("a.go", "/*\nPackage a does x.\nIt also y.\n*/\npackage a\n"), [("C1", 2)])

    def test_windows_line_endings_lex_like_newlines(self):
        text = "// one\n// two\nfunc f() {}\n/* three\n   four */\nvar s = `\n// five\n`\n//go:generate x\n"
        self.assertEqual(found("a.go", text.replace("\n", "\r\n")), found("a.go", text))
        self.assertEqual(found("a.go", text), [("C1", 1), ("C1", 4)])


class TestDirectives(unittest.TestCase):
    def test_a_directive_splits_a_comment_block(self):
        self.assertEqual(found("a.go", "// content holds files.\n//go:embed static\nvar content embed.FS\n"), [])

    def test_two_generate_directives_are_not_prose(self):
        self.assertEqual(found("a.go", "//go:generate stringer -type=A\n//go:generate mockgen -source=a.go\n"), [])

    def test_a_build_constraint_and_its_legacy_form_are_not_prose(self):
        self.assertEqual(found("a.go", "//go:build linux\n// +build linux\n\npackage a\n"), [])

    def test_a_prose_comment_after_a_directive_is_still_judged(self):
        self.assertEqual(found("a.go", "//go:generate x\n// see ADR-9\n"), [("C3", 2)])

    def test_a_directive_is_not_read_for_references_or_length(self):
        self.assertEqual(found("a.go", "//go:generate gen -doc docs/ADR-9.md %s\n" % LONG), [])

    def test_tool_line_export_and_extern_directives_are_not_prose(self):
        text = "//nolint:errcheck\n//line a.go:10\n//export Add\n//extern add\n//lint:ignore U1000 x\n"
        self.assertEqual(found("a.go", text), [])

    def test_an_indented_directive_is_a_directive(self):
        self.assertEqual(found("a.go", "func f() {\n\t//go:noinline\n\t//go:nosplit\n}\n"), [])

    def test_a_directive_after_code_is_just_a_comment(self):
        self.assertEqual(found("a.go", "x := 1 //go:noinline ADR-9\n"), [("C3", 1)])

    def test_comments_that_only_look_like_directives_are_prose(self):
        for text in ("// go:build linux\n// two\n", "//go: build\n// two\n", "//Go:build x\n// two\n",
                     "// nolint\n// two\n", "//nolintx\n// two\n", "//lines a.go:10\n// two\n",
                     "// +builder x\n// two\n"):
            self.assertEqual(found("a.go", text), [("C1", 1)], text)

    def test_a_directive_inside_a_raw_string_is_content(self):
        self.assertEqual(found("a.go", "var s = `\n//go:build x\n// see ADR-9\n`\n"), [])

    def test_a_directive_inside_a_block_comment_is_block_text(self):
        self.assertEqual(found("a.go", "/*\none\n//go:build x\n*/\n"), [("C1", 2)])


class TestDirectiveReasons(unittest.TestCase):
    def test_a_reason_after_a_directive_is_read_for_references(self):
        self.assertEqual(found("a.go", "//nolint:gosec // see ADR-12\nx := 1\n"), [("C3", 1)])
        self.assertEqual(comments("a.go", "//nolint:gosec // see ADR-12\nx := 1\n"), [["// see ADR-12"], []])

    def test_a_plain_reason_after_a_directive_passes(self):
        self.assertEqual(found("a.go", "//nolint:gosec // fine\n"), [])

    def test_a_long_reason_after_a_directive_is_an_overlong_comment_line(self):
        self.assertEqual(found("a.go", "//nolint:gosec // %s\n" % LONG), [("C7", 1)])

    def test_a_reason_is_a_trailing_comment_that_joins_no_block(self):
        self.assertEqual(found("a.go", "// one\n//nolint:gosec // two\n// three\nx := 1\n"), [])

    def test_a_directive_without_a_reason_is_still_not_read(self):
        self.assertEqual(found("a.go", "//go:embed docs/*\nvar d embed.FS\n"), [])

    def test_a_reason_may_follow_a_tab(self):
        self.assertEqual(found("a.go", "//nolint:gosec\t// see ADR-12\nx := 1\n"), [("C3", 1)])
        self.assertEqual(comments("a.go", "//nolint:gosec\t// see ADR-12\n"), [["// see ADR-12"]])

    def test_slashes_inside_a_quoted_argument_start_no_reason(self):
        self.assertEqual(found("a.go", '//go:generate sh -c "echo // see ADR-9"\n'), [])
        self.assertEqual(found("a.go", '//go:generate sh -c "a \\" // see ADR-9"\n'), [])
        self.assertEqual(found("a.go", "//go:generate sh -c `echo // see ADR-9`\n"), [])

    def test_a_reason_after_a_quoted_argument_is_read(self):
        self.assertEqual(found("a.go", '//go:generate sh -c "a" // see ADR-9\n'), [("C3", 1)])
        self.assertEqual(found("a.go", "//go:generate sh -c `a` // see ADR-9\n"), [("C3", 1)])

    def test_an_unclosed_quote_in_a_directive_leaves_no_reason(self):
        self.assertEqual(found("a.go", '//go:generate sh -c "echo // see ADR-9\n'), [])
        self.assertEqual(found("a.go", "//go:generate sh -c `echo // see ADR-9\n"), [])

    def test_a_bare_nolint_is_a_directive(self):
        self.assertEqual(found("a.go", "//nolint\n// one line\nx := 1\n"), [])
        self.assertEqual(found("a.go", "x := 1\n//nolint\t\n// one line\n"), [])

    def test_a_reason_after_a_bare_nolint_is_read(self):
        self.assertEqual(found("a.go", "//nolint // see ADR-9\n"), [("C3", 1)])


if __name__ == "__main__":
    unittest.main()
