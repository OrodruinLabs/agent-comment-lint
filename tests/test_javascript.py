"""JavaScript and TypeScript lexing: strings, templates and regex literals never read as comments."""
import unittest

from agent_comment_lint import engine
from agent_comment_lint.lexers import LexError, family_for
from support import LONG, comments, found


class TestScope(unittest.TestCase):
    def test_module_extensions_are_covered(self):
        for name in ("a.mjs", "a.cjs", "a.mts", "a.cts", "a.js", "a.ts"):
            self.assertEqual(family_for(name).name, "javascript", name)
        for name in ("a.tsx", "a.jsx"):
            self.assertEqual(family_for(name).name, "jsx", name)

    def test_a_planted_violation_in_a_module_file_is_reported(self):
        self.assertEqual(found("scripts/check.mjs", "// one\n// two\nexport {};\n"), [("C1", 1)])
        self.assertEqual(found("scripts/check.cjs", "// see ADR-0001\n"), [("C3", 1)])


class TestStrings(unittest.TestCase):
    def test_a_url_in_a_single_quoted_string_is_not_a_comment(self):
        self.assertEqual(comments("a.ts", "const u = 'http://host/ADR-0001';\n"), [[]])

    def test_a_url_in_a_double_quoted_string_is_not_a_comment(self):
        self.assertEqual(comments("a.ts", 'const u = "http://host/ADR-0001";\n'), [[]])

    def test_an_escaped_quote_does_not_end_the_string(self):
        self.assertEqual(comments("a.ts", "const u = 'it\\'s // fine';\n"), [[]])

    def test_a_string_continued_with_a_backslash_spans_lines(self):
        text = "const u = 'one \\\n// ADR-0001 \\\n// two';\n"
        self.assertEqual(found("a.ts", text), [])

    def test_a_comment_after_a_string_is_still_reported(self):
        self.assertEqual(found("a.ts", "const u = 'http://host'; // see ADR-0001\n"), [("C3", 1)])


class TestTemplateLiterals(unittest.TestCase):
    def test_a_url_with_an_interpolation_is_not_a_comment(self):
        self.assertEqual(comments("a.ts", "const u = `http://localhost:${port}/ADR-0001`;\n"), [[]])

    def test_a_block_opener_inside_a_template_swallows_nothing(self):
        text = "expect(x, `the /v2/* route.`).toBe(1);\nconst y = 2;\n// see ADR-0001\n"
        self.assertEqual(comments("a.ts", text), [[], [], ["// see ADR-0001"]])

    def test_css_in_a_raw_template_is_not_an_overlong_comment(self):
        text = "const css = String.raw`:root { --a: 1px; } /* %s */`;\n" % LONG
        self.assertEqual(found("scripts/lib/token-record.test.ts", text), [])

    def test_a_tagged_template_is_content(self):
        self.assertEqual(found("a.ts", "const q = sql`select 1 -- ADR-0001 // %s`;\n" % LONG), [])

    def test_a_comment_after_a_template_on_the_same_line_is_still_reported(self):
        text = "const css = String.raw`/* not a comment */`; // see ADR-0001\n"
        self.assertEqual(found("a.ts", text), [("C3", 1)])
        self.assertEqual(comments("a.ts", text), [["// see ADR-0001"]])

    def test_a_string_inside_an_interpolation_is_content(self):
        self.assertEqual(comments("a.ts", "const u = `a ${f('// x', \"/* y\")} b // c`;\n"), [[]])

    def test_a_template_inside_an_interpolation_is_content(self):
        self.assertEqual(comments("a.ts", "const u = `a ${`b ${c} // d`} // e`;\n"), [[]])

    def test_a_comment_inside_an_interpolation_is_a_comment(self):
        text = "const u = `a ${b /* see ADR-0001 */} c`;\n"
        self.assertEqual(found("a.ts", text), [("C3", 1)])

    def test_a_brace_pair_inside_an_interpolation_does_not_end_it(self):
        self.assertEqual(comments("a.ts", "const u = `${{ a: 1 }.a + \"`\"} // still text`;\n"), [[]])

    def test_an_escaped_backtick_does_not_end_the_template(self):
        self.assertEqual(comments("a.ts", "const u = `a \\` // b`;\n"), [[]])

    def test_comment_shaped_lines_inside_a_template_are_not_a_prose_block(self):
        text = "const t = `\n// one\n// two\n * three\n * four\n`;\n"
        self.assertEqual(found("a.ts", text), [])

    def test_a_block_after_a_multi_line_template_is_still_scored(self):
        text = "const t = `\n// one\n`;\n// two\n// three\n"
        self.assertEqual(found("a.ts", text), [("C1", 4)])


class TestRegexLiterals(unittest.TestCase):
    def test_a_regex_holding_comment_markers_opens_no_comment(self):
        text = 'css = css.replace(/\\/\\*[\\s\\S]*?\\*\\//g, "");\nconst n = 1;\n'
        self.assertEqual(comments("a.mjs", text), [[], []])

    def test_a_regex_holding_slashes_in_a_class_opens_no_comment(self):
        self.assertEqual(comments("a.ts", "const r = /[//*]+/;\n"), [[]])

    def test_a_regex_holding_quotes_opens_no_string(self):
        text = "const r = /['\"]([^'\"]+)['\"]/; // see ADR-0001\n"
        self.assertEqual(found("a.ts", text), [("C3", 1)])

    def test_a_regex_after_a_keyword_is_a_regex(self):
        self.assertEqual(comments("a.ts", "function f(s) { return /https?:\\/\\//.test(s); }\n"), [[]])

    def test_a_regex_after_a_closing_brace_is_a_regex(self):
        self.assertEqual(comments("a.ts", "if (a) {}\n/x[//]y/.test(s);\n"), [[], []])
        self.assertEqual(comments("a.ts", "if (a) { b(); } /x[//]y/.test(s);\n"), [[]])

    def test_a_comment_after_a_regex_is_still_reported(self):
        self.assertEqual(found("a.ts", "const r = /a\\/\\/b/g; // see ADR-0001\n"), [("C3", 1)])


class TestDivisionIsNotARegex(unittest.TestCase):
    """A slash after a value divides; read as a regex, its class would swallow the comment that follows."""

    TRAP = " / b[ // see ADR-0001 ] /\n"

    def assert_divides(self, path, before):
        self.assertEqual(found(path, "const x = " + before + self.TRAP), [("C3", 1)], before)

    def test_after_an_identifier(self):
        self.assert_divides("a.ts", "a")

    def test_after_a_number(self):
        self.assert_divides("a.ts", "2")

    def test_after_a_closing_parenthesis(self):
        self.assert_divides("a.ts", "(a + b)")

    def test_after_a_closing_bracket(self):
        self.assert_divides("a.ts", "a[0]")

    def test_after_a_non_null_assertion(self):
        self.assert_divides("a.ts", "a!")

    def test_after_a_string(self):
        self.assert_divides("a.ts", "'a'")

    def test_a_negation_still_lets_a_regex_start(self):
        self.assertEqual(comments("a.ts", "const x = !/[//]/.test(s);\n"), [[]])

    def test_a_jsx_closing_tag_is_not_a_regex(self):
        self.assertEqual(found("a.tsx", "const e = <b>x</b>; f([ // see ADR-0001 ]) /\n"), [("C3", 1)])
        self.assertEqual(found("a.tsx", "const e = <b>x</b>; {/* see ADR-0001 */}</div>\n"), [("C3", 1)])

    def test_a_regex_never_runs_past_the_end_of_its_line(self):
        text = "const x = y >\n  / 2 + f('x');\nconst z = '/';\n"
        self.assertEqual(comments("a.ts", text), [[], [], []])

    def test_a_slash_closed_only_by_a_comment_opener_divides(self):
        self.assertEqual(found("a.ts", "const x = i++ / 2; // see ADR-0001\n"), [("C3", 1)])
        self.assertEqual(found("a.ts", "const x = i++ / 2; /* see ADR-0001 */\n"), [("C3", 1)])


class TestLeadingStar(unittest.TestCase):
    def test_a_multiplication_at_the_start_of_a_line_is_not_prose(self):
        self.assertEqual(found("a.ts", "const x = a\n  * b\n  * c;\n"), [])

    def test_a_generator_method_is_not_prose(self):
        self.assertEqual(found("a.js", "class A {\n  *one() {}\n  *two() {}\n}\n"), [])

    def test_star_lines_inside_a_block_comment_are_prose(self):
        self.assertEqual(found("a.ts", "/**\n * one\n * two\n */\n"), [("C1", 2)])



class TestBlockComments(unittest.TestCase):
    """A `/* */` comment that spans lines is one block wherever it opens; the lexer places it, not the rules."""

    def test_a_block_opened_after_code_is_scored_from_its_opening_line(self):
        text = "foo(); /* this is a long\n explanation that wraps\n across lines */\n"
        findings = engine.check_text("a.ts", text).findings
        self.assertEqual([(finding.rule, finding.line, finding.end_line, finding.message) for finding in findings],
                         [("C1", 1, 3, "3-line prose block (limit 1)")])

    def test_star_lines_of_a_block_opened_after_code_are_prose(self):
        self.assertEqual(found("a.ts", "const x = 1; /* note\n * one\n * two\n */\n"), [("C1", 1)])

    def test_a_one_line_block_after_code_still_passes(self):
        self.assertEqual(found("a.ts", "foo(); /* one */\nbar(); /* two */\n"), [])

    def test_a_line_that_closes_one_block_and_opens_the_next_belongs_to_both(self):
        text = "/* a\n b */ x(); /* c\n d */\n"
        self.assertEqual(found("a.ts", text), [("C1", 1), ("C1", 2)])
        self.assertEqual(found("a.ts", "/* a\n */ x(); /* c\n */\n"), [])

    def test_a_block_after_a_one_line_comment_on_the_same_line_is_scored(self):
        self.assertEqual(found("a.ts", "/* a */ x(); /* b\n c */\n"), [("C1", 1)])

    def test_a_block_opened_on_the_line_a_template_closes_is_scored(self):
        self.assertEqual(found("a.ts", "const t = `x\ny`; /* one\n two */\n"), [("C1", 2)])

    def test_complete_tags_in_a_block_opened_after_code_do_not_count(self):
        self.assertEqual(found("a.ts", "foo(); /* @param a one\n * @param b two\n */\n"), [])

    def test_an_unterminated_block_comment_is_refused_with_its_opening_line(self):
        with self.assertRaises(LexError) as caught:
            found("a.ts", "const a = 1;\nfoo(); /* never closes\n// see ADR-0001\n")
        self.assertEqual((caught.exception.line, caught.exception.message), (2, "unterminated block comment"))

    def test_an_unclosed_opener_in_jsx_text_is_refused_not_swallowed(self):
        with self.assertRaises(LexError) as caught:
            found("a.tsx", "const e = <p>\n  all of src/* is covered</p>;\n// see ADR-0001\n")
        self.assertEqual(caught.exception.line, 2)


class TestUnterminated(unittest.TestCase):
    def test_an_unterminated_template_is_refused_with_its_opening_line(self):
        with self.assertRaises(LexError) as caught:
            found("a.ts", "const a = 1;\nconst t = `never closes\n// see ADR-0001\n")
        self.assertEqual((caught.exception.line, caught.exception.message), (2, "unterminated template literal"))

    def test_an_unterminated_interpolation_is_refused(self):
        with self.assertRaises(LexError) as caught:
            found("a.ts", "const t = `a ${b\n")
        self.assertEqual(caught.exception.line, 1)

    def test_an_unterminated_string_is_refused_with_its_line(self):
        with self.assertRaises(LexError) as caught:
            found("a.ts", "const a = 1;\nconst s = 'never closes;\n")
        self.assertEqual((caught.exception.line, caught.exception.message), (2, "unterminated string literal"))

    def test_an_apostrophe_in_jsx_text_is_plain_text(self):
        text = "const e = <p>Don't stop</p>; // see ADR-0001\n"
        self.assertEqual(found("a.tsx", text), [("C3", 1)])

    def test_a_terminated_file_is_not_refused(self):
        self.assertEqual(found("a.ts", "const t = `a ${b} c`;\nconst s = 'd';\n"), [])


class TestLineAccounting(unittest.TestCase):
    def test_one_line_out_per_line_in_whatever_the_line_break(self):
        text = "const a = `x\r\ny`;\r\n// see ADR-0001\r\n"
        self.assertEqual(found("a.ts", text), [("C3", 3)])

    def test_an_empty_file_has_no_lines(self):
        self.assertEqual(family_for("a.ts").lex(""), [])
