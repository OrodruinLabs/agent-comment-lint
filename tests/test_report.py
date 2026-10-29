"""The report: a fixed order, `path:line: rule: message` lines, and the three exit codes."""
import json
import unittest

from agent_comment_lint import report
from agent_comment_lint.rules import Finding


def make(findings=(), errors=(), scanned=3):
    return report.Report("all", scanned, list(findings), list(errors), 0)


B7 = ("b.ts", Finding("C7", 7, 7, "comment line is 130 chars (limit 120)"))
B2 = ("b.ts", Finding("C1", 2, 4, "3-line prose block (limit 1)"))
A9 = ("a.ts", Finding("C3", 9, 9, "governance reference 'ADR-1'"))
A9_C1 = ("a.ts", Finding("C1", 9, 10, "2-line prose block (limit 1)"))


class TestExitCode(unittest.TestCase):
    def test_clean_is_zero(self):
        self.assertEqual(report.exit_code(make()), 0)

    def test_findings_are_one(self):
        self.assertEqual(report.exit_code(make([B7])), 1)

    def test_an_error_is_two_even_beside_findings(self):
        self.assertEqual(report.exit_code(make([B7], [("a.ts", 3, "unterminated string literal")])), 2)


class TestText(unittest.TestCase):
    def test_each_finding_is_path_line_rule_message(self):
        out, _err = report.as_text(make([B2]))
        self.assertEqual(out.splitlines()[0], "b.ts:2: C1: 3-line prose block (limit 1)")

    def test_findings_are_ordered_by_path_then_line_then_rule(self):
        out, _err = report.as_text(make([B7, A9, B2, A9_C1]))
        self.assertEqual([line.split(": ")[0] + " " + line.split(": ")[1] for line in out.splitlines()[:4]],
                         ["a.ts:9 C1", "a.ts:9 C3", "b.ts:2 C1", "b.ts:7 C7"])

    def test_the_order_given_does_not_change_the_output(self):
        self.assertEqual(report.as_text(make([B7, A9, B2])), report.as_text(make([B2, B7, A9])))

    def test_the_summary_counts_violations_and_files(self):
        out, _err = report.as_text(make([B7, A9, B2]))
        self.assertEqual(out.splitlines()[-1], "agent-comment-lint: 3 violation(s) in 2 of 3 file(s) scanned.")

    def test_a_clean_run_says_so(self):
        self.assertEqual(report.as_text(make()), ("agent-comment-lint: clean, 3 file(s) scanned.\n", ""))

    def test_an_error_names_the_file_and_line_and_withholds_the_verdict(self):
        out, err = report.as_text(make([], [("a.ts", 3, "unterminated string literal"), ("git", None, "no base")]))
        self.assertEqual(err.splitlines(), ["a.ts:3: could not scan: unterminated string literal",
                                            "git: could not scan: no base",
                                            "agent-comment-lint: no verdict, 2 problem(s) stopped the scan."])
        self.assertNotIn("clean", out)


class TestJson(unittest.TestCase):
    def test_the_document_carries_findings_counts_and_exit_code(self):
        document = json.loads(report.as_json(make([B7, A9, B2])))
        self.assertEqual(document["exit_code"], 1)
        self.assertEqual(document["counts"], {"C1": 1, "C3": 1, "C7": 1})
        self.assertEqual(document["files_scanned"], 3)
        self.assertEqual(document["findings"][0], {"path": "a.ts", "line": 9, "end_line": 9, "rule": "C3",
                                                   "message": "governance reference 'ADR-1'"})
        self.assertEqual([item["path"] for item in document["findings"]], ["a.ts", "b.ts", "b.ts"])

    def test_errors_are_listed_and_the_exit_code_is_two(self):
        document = json.loads(report.as_json(make([], [("a.ts", 3, "unterminated string literal")])))
        self.assertEqual(document["exit_code"], 2)
        self.assertEqual(document["errors"], [{"path": "a.ts", "line": 3, "message": "unterminated string literal"}])

    def test_the_same_run_serializes_to_the_same_bytes(self):
        self.assertEqual(report.as_json(make([B7, A9, B2])), report.as_json(make([B2, A9, B7])))


HEADER = "Blocked: x\n" + report.HOOK_SCOPE
CLOSING = ("Fix the comment and retry the same tool call.",)


def finding(rule, line, end_line, message):
    return Finding(rule, line, end_line, message)


class TestHookText(unittest.TestCase):
    def test_a_hook_report_quotes_the_comment_and_says_how_to_fix_it(self):
        result = report.Report("hook", 1, [("a.ts", finding("C1", 1, 2, "2-line prose block (limit 1)"))], [], 0)
        text = report.hook_text(result, {"a.ts": "// one\n// two\nconst a = 1;\n"}, HEADER, CLOSING)
        self.assertEqual(text.splitlines()[:6], [
            "Blocked: x",
            "Only the lines this write adds or changes are judged; comments elsewhere in the file are fine.",
            "a.ts:1: C1: 2-line prose block (limit 1)",
            "    // one",
            "    // two",
            "  Fix: " + report.FIXES["C1"],
        ])
        self.assertTrue(text.endswith("Fix the comment and retry the same tool call.\n"))

    def test_a_long_block_shows_six_lines_and_counts_the_rest(self):
        body = "".join("// line %d\n" % n for n in range(1, 10))
        result = report.Report("hook", 1, [("a.ts", finding("C1", 1, 9, "9-line prose block (limit 1)"))], [], 0)
        text = report.hook_text(result, {"a.ts": body}, HEADER, CLOSING)
        self.assertIn("    // line 6\n    \u2026 3 more line(s)\n", text)
        self.assertNotIn("// line 7", text)

    def test_a_long_line_is_cut_at_the_excerpt_width(self):
        line = "x = 1  # " + "y" * 150
        result = report.Report("hook", 1, [("a.py", finding("C7", 1, 1, "159-character line (limit 120)"))], [], 0)
        excerpt = report.hook_text(result, {"a.py": line + "\n"}, HEADER, CLOSING).splitlines()[3]
        self.assertEqual(excerpt, "    " + line[:119] + "\u2026")

    def test_errors_keep_their_form_and_get_no_closing_lines(self):
        result = report.Report("hook", 0, [], [("a.ts", 3, "unterminated string")], 0)
        text = report.hook_text(result, {}, HEADER, CLOSING)
        self.assertIn("a.ts:3: could not scan: unterminated string\n", text)
        self.assertNotIn("retry", text)

    def test_a_finding_with_no_text_keeps_its_finding_and_fix_lines(self):
        result = report.Report("hook", 1, [("a.ts", finding("C3", 4, 4, "governance reference 'ADR-1'"))], [], 0)
        lines = report.hook_text(result, {}, HEADER, CLOSING).splitlines()
        self.assertEqual(lines[2:4], ["a.ts:4: C3: governance reference 'ADR-1'", "  Fix: " + report.FIXES["C3"]])
