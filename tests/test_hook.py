"""The hook's reading of a PreToolUse event: which file, what it would hold, which lines the write touched."""
import time
import unittest

from agent_comment_lint import hook


PERIODIC = ["alpha = 1", "", "beta = 2"]


def lines(rows):
    return "".join(row + "\n" for row in rows)


def target(tool, **tool_input):
    return hook.target({"tool_name": tool, "tool_input": dict(tool_input, file_path="a.ts")})


class TestTarget(unittest.TestCase):
    def test_a_write_names_its_file(self):
        found = target("Edit", old_string="a", new_string="b")
        self.assertEqual((found.tool, found.path), ("Edit", "a.ts"))

    def test_a_tool_that_writes_no_file_is_not_a_target(self):
        self.assertIsNone(hook.target({"tool_name": "Read", "tool_input": {"file_path": "a.ts"}}))

    def test_input_that_is_not_the_event_is_refused(self):
        for event in ([], {"tool_input": {"file_path": "a.ts"}}, {"tool_name": "Write"},
                      {"tool_name": "Write", "tool_input": {}},
                      {"tool_name": "Write", "tool_input": {"file_path": ""}}):
            with self.subTest(event=event):
                with self.assertRaises(hook.HookInputError):
                    hook.target(event)


class TestProposedText(unittest.TestCase):
    def test_a_write_is_its_content(self):
        self.assertEqual(hook.proposed_text(target("Write", content="x\n"), "old\n"), "x\n")

    def test_an_edit_replaces_its_one_occurrence(self):
        self.assertEqual(hook.proposed_text(target("Edit", old_string="b", new_string="c"), "a\nb\n"), "a\nc\n")

    def test_a_newline_only_edit_matches_a_file_with_windows_line_endings(self):
        edit = target("Edit", old_string="b\n", new_string="// x\n// y\nb\n")
        self.assertEqual(hook.proposed_text(edit, "a\r\nb\r\n"), "a\r\n// x\r\n// y\r\nb\r\n")

    def test_an_exact_match_wins_over_the_line_ending_fallback(self):
        edit = target("Edit", old_string="a\r\n", new_string="z\r\n")
        self.assertEqual(hook.proposed_text(edit, "a\r\nb\r\n"), "z\r\nb\r\n")

    def test_a_newline_only_edit_the_tool_would_refuse_still_proposes_nothing(self):
        edit = target("Edit", old_string="zzz\n", new_string="c\n")
        self.assertIsNone(hook.proposed_text(edit, "a\r\nb\r\n"))

    def test_replace_all_replaces_every_occurrence(self):
        edit = target("Edit", old_string="b", new_string="c", replace_all=True)
        self.assertEqual(hook.proposed_text(edit, "b\nb\n"), "c\nc\n")

    def test_an_edit_the_tool_would_refuse_proposes_nothing(self):
        cases = [("missing old string", target("Edit", old_string="z", new_string="c"), "a\n"),
                 ("ambiguous without replace_all", target("Edit", old_string="b", new_string="c"), "b\nb\n"),
                 ("no such file", target("Edit", old_string="b", new_string="c"), None),
                 ("empty old string on a file with text", target("Edit", old_string="", new_string="c"), "a\n")]
        for name, edit, current in cases:
            with self.subTest(name):
                self.assertIsNone(hook.proposed_text(edit, current))

    def test_an_empty_old_string_creates_a_missing_file(self):
        self.assertEqual(hook.proposed_text(target("Edit", old_string="", new_string="c\n"), None), "c\n")

    def test_multi_edit_applies_its_edits_in_order(self):
        edits = [{"old_string": "a", "new_string": "b"}, {"old_string": "b\nb", "new_string": "c"}]
        self.assertEqual(hook.proposed_text(target("MultiEdit", edits=edits), "a\nb\n"), "c\n")

    def test_multi_edit_with_one_refused_edit_proposes_nothing(self):
        edits = [{"old_string": "a", "new_string": "b"}, {"old_string": "z", "new_string": "c"}]
        self.assertIsNone(hook.proposed_text(target("MultiEdit", edits=edits), "a\n"))

    def test_a_non_string_edit_is_refused(self):
        cases = [target("Write", content=None), target("Edit", old_string=1, new_string="b"),
                 target("MultiEdit", edits="x"), target("MultiEdit", edits=["x"]),
                 target("Edit", old_string="a", new_string="b", replace_all="true"),
                 target("Edit", old_string="a", new_string="b", replace_all=None)]
        for edit in cases:
            with self.subTest(edit=edit.tool_input):
                with self.assertRaises(hook.HookInputError):
                    hook.proposed_text(edit, "a\n")


class TestChangedRanges(unittest.TestCase):
    def test_an_insertion_is_its_own_lines(self):
        self.assertEqual(hook.changed_ranges("a\nd\n", "a\nb\nc\nd\n"), [(2, 3)])

    def test_a_replacement_is_the_new_lines(self):
        self.assertEqual(hook.changed_ranges("a\nb\nc\n", "a\nx\nc\n"), [(2, 2)])

    def test_a_new_file_is_every_line(self):
        self.assertEqual(hook.changed_ranges(None, "a\nb\n"), [(1, 2)])

    def test_a_deletion_or_no_change_touches_no_line(self):
        self.assertEqual(hook.changed_ranges("a\nb\n", "a\n"), [])
        self.assertEqual(hook.changed_ranges("a\n", "a\n"), [])

    def test_windows_line_endings_compare_as_lines(self):
        self.assertEqual(hook.changed_ranges("a\r\nc\r\n", "a\r\nb\r\nc\r\n"), [(2, 2)])

    def test_one_inserted_line_in_a_repetitive_file_is_only_that_line(self):
        rows = PERIODIC * 3333
        after = rows[:1] + ["// new"] + rows[1:]
        self.assertEqual(hook.changed_ranges(lines(rows), lines(after)), [(2, 2)])

    def test_a_one_line_edit_to_a_50000_line_file_takes_under_a_second(self):
        rows = (PERIODIC * 16667)[:50000]
        after = list(rows)
        after[24999] = "// changed"
        started = time.perf_counter()
        found = hook.changed_ranges(lines(rows), lines(after))
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertEqual(found, [(25000, 25000)])

    def test_replace_all_far_apart_reports_only_those_two_lines(self):
        rows = ["k"] + PERIODIC * 700 + ["k"]
        after = ["z"] + PERIODIC * 700 + ["z"]
        self.assertEqual(hook.changed_ranges(lines(rows), lines(after)), [(1, 1), (2102, 2102)])
