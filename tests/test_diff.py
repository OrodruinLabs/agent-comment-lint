"""Diff parsing: only the lines a hunk header announces are content, whatever they look like."""
import unittest

from agent_comment_lint.diff import parse_diff_ranges

HEADER = "diff --git a/a.ts b/a.ts\nindex 1111111..2222222 100644\n--- a/a.ts\n+++ b/a.ts\n"


class TestHeaderShapedContent(unittest.TestCase):
    def test_an_added_line_that_starts_with_two_pluses_is_not_a_file_header(self):
        text = HEADER + "@@ -1,0 +2 @@ let i = 0;\n+++ i;\n@@ -2,0 +4,2 @@ let j = 0;\n+// one\n+// two\n"
        self.assertEqual(parse_diff_ranges(text), {"a.ts": [(2, 2), (4, 5)]})

    def test_a_removed_and_an_added_line_shaped_like_a_header_pair_are_content(self):
        text = HEADER + "@@ -2 +2 @@ let i = 9;\n--- i;\n+++ i;\n@@ -3,0 +4 @@ let j = 0;\n+// one\n"
        self.assertEqual(parse_diff_ranges(text), {"a.ts": [(2, 2), (4, 4)]})

    def test_an_added_line_shaped_like_a_hunk_header_is_content(self):
        text = HEADER + "@@ -1,0 +2 @@\n+@@ -1,0 +90,5 @@\n@@ -2,0 +4 @@\n+// one\n"
        self.assertEqual(parse_diff_ranges(text), {"a.ts": [(2, 2), (4, 4)]})

    def test_a_no_newline_note_does_not_end_the_hunk_body(self):
        text = HEADER + "@@ -3 +3 @@\n-old\n\\ No newline at end of file\n+++ i;\n\\ No newline at end of file\n" \
            + "diff --git a/b.ts b/b.ts\n--- a/b.ts\n+++ b/b.ts\n@@ -1,0 +2 @@\n+x\n"
        self.assertEqual(parse_diff_ranges(text), {"a.ts": [(3, 3)], "b.ts": [(2, 2)]})

    def test_a_form_feed_inside_an_added_line_does_not_split_it(self):
        text = HEADER + "@@ -1,0 +2 @@\n+a\x0c+++ b/other.ts\n@@ -2,0 +4 @@\n+// one\n"
        self.assertEqual(parse_diff_ranges(text), {"a.ts": [(2, 2), (4, 4)]})

    def test_context_lines_are_counted_on_both_sides(self):
        text = HEADER + "@@ -1,3 +1,4 @@\n a\n+++ i;\n b\n c\n@@ -9,0 +11 @@\n+x\n"
        self.assertEqual(parse_diff_ranges(text), {"a.ts": [(1, 4), (11, 11)]})

    def test_the_file_after_a_hunk_is_still_found(self):
        text = HEADER + "@@ -1,0 +2 @@\n+x\ndiff --git a/b.ts b/b.ts\n--- a/b.ts\n+++ b/b.ts\n@@ -1 +1 @@\n-y\n+z\n"
        self.assertEqual(parse_diff_ranges(text), {"a.ts": [(2, 2)], "b.ts": [(1, 1)]})


class TestQuotedPaths(unittest.TestCase):
    """Git writes a name that holds a quote, a backslash or a control character in C-style quotes."""

    def ranges_for(self, quoted):
        text = "diff --git %s %s\n--- /dev/null\n+++ %s\n@@ -0,0 +1,2 @@\n+// one\n+// two\n" % (quoted, quoted, quoted)
        return parse_diff_ranges(text)

    def test_an_escaped_quote_backslash_and_tab_are_read_back(self):
        self.assertEqual(self.ranges_for(r'"b/we\"ird.cs"'), {'we"ird.cs': [(1, 2)]})
        self.assertEqual(self.ranges_for(r'"b/back\\slash.cs"'), {"back\\slash.cs": [(1, 2)]})
        self.assertEqual(self.ranges_for(r'"b/tab\there.cs"'), {"tab\there.cs": [(1, 2)]})

    def test_every_named_control_escape_is_read_back(self):
        self.assertEqual(self.ranges_for(r'"b/\a\b\f\n\r\v.cs"'), {"\a\b\f\n\r\v.cs": [(1, 2)]})

    def test_octal_bytes_are_read_as_utf_8(self):
        self.assertEqual(self.ranges_for(r'"b/caf\303\251 \001.cs"'), {"caf\u00e9 \x01.cs": [(1, 2)]})

    def test_a_letter_outside_ascii_left_as_it_is_inside_quotes_is_kept(self):
        self.assertEqual(self.ranges_for('"b/caf\u00e9 \\"x\\".cs"'), {'caf\u00e9 "x".cs': [(1, 2)]})

    def test_a_backslash_before_a_digit_run_is_not_confused_with_an_escaped_backslash(self):
        self.assertEqual(self.ranges_for(r'"b/a\\101.cs"'), {"a\\101.cs": [(1, 2)]})

    def test_a_name_that_only_starts_with_a_quote_is_left_alone(self):
        self.assertEqual(self.ranges_for('"b/odd.cs'), {'"b/odd.cs': [(1, 2)]})

    def test_a_quoted_null_device_is_not_a_file(self):
        self.assertEqual(parse_diff_ranges('--- "a/we\\"ird.cs"\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n'), {})
