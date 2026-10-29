"""The per-agent adapters: each turns one agent's hook event into the writes the hook judges."""
import json
import os
import unittest

from agent_comment_lint import codex_patch, hook

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents")
CLAUDE_WRITE = {"tool_name": "Write", "tool_input": {"file_path": "a.ts", "content": "const a = 1;\n"}}


def fixture(name):
    with open(os.path.join(FIXTURES, name + ".json"), encoding="utf-8") as handle:
        return json.load(handle)


class AdapterContract:
    """Mixin for an agent's test class: sets `agent`, `write_fixture`, `non_write_fixture`, `pathless_fixture`."""

    agent = write_fixture = non_write_fixture = pathless_fixture = None

    def test_the_write_fixture_yields_a_target(self):
        self.assertGreaterEqual(len(hook.targets(fixture(self.write_fixture), self.agent)), 1)

    def test_the_non_write_fixture_yields_nothing(self):
        self.assertEqual(hook.targets(fixture(self.non_write_fixture), self.agent), [])

    def test_the_pathless_fixture_is_refused(self):
        with self.assertRaises(hook.HookInputError):
            hook.targets(fixture(self.pathless_fixture), self.agent)


class TestClaudeAdapter(unittest.TestCase):
    def test_the_claude_adapter_is_the_default(self):
        self.assertEqual(hook.targets(CLAUDE_WRITE, "claude"), [hook.target(CLAUDE_WRITE)])

    def test_a_tool_that_writes_nothing_yields_no_target(self):
        self.assertEqual(hook.targets({"tool_name": "Read", "tool_input": {}}, "claude"), [])

    def test_an_event_that_is_not_an_object_is_refused(self):
        with self.assertRaises(hook.HookInputError):
            hook.targets([], "claude")

    def test_a_target_applies_loosely_unless_told_otherwise(self):
        self.assertFalse(hook.target(CLAUDE_WRITE).must_apply)


class TestRegistry(unittest.TestCase):
    def test_every_adapter_has_a_title_and_no_title_is_orphaned(self):
        self.assertEqual(sorted(hook.TITLES), sorted(hook.ADAPTERS))


def at_repo(path):
    """A patch path as the adapter resolves it against the documented fixtures' session directory, /repo."""
    return os.path.join("/repo", path)


def codex_event(patch, **fields):
    return dict(fixture("codex-write"), tool_input={"command": patch}, **fields)


def patch(*lines):
    return "\n".join(("*** Begin Patch",) + lines + ("*** End Patch",))


def hunk(old, new, anchor=None, at_end=False, context=()):
    return codex_patch.CodexHunk(anchor, old, new, at_end, context)


class TestCodexAdapter(AdapterContract, unittest.TestCase):
    agent, write_fixture, non_write_fixture, pathless_fixture = "codex", "codex-write", "codex-read", "codex-pathless"

    GREET = 'def greet(name):\n    return "Hello, " + name\n'

    def targets(self, event):
        return hook.targets(event, "codex")

    def test_an_added_file_is_a_write_of_its_content(self):
        path = at_repo("src/greet.py")
        self.assertEqual(self.targets(fixture("codex-write")),
                         [hook.Target("Write", path, {"file_path": path, "content": self.GREET})])

    def test_an_updated_file_is_a_patch_that_must_apply(self):
        path = at_repo("src/app.py")
        found = hunk(['    name = "world"', '    print("hi")'], ['    name = "world"', '    print("hello", name)'],
                     anchor="def main():", context=((0, 0),))
        self.assertEqual(self.targets(fixture("codex-edit")),
                         [hook.Target("CodexPatch", path, {"file_path": path, "hunks": [found]}, True)])

    def test_a_deleted_file_is_not_judged(self):
        self.assertEqual(self.targets(fixture("codex-delete")), [])

    def test_a_patch_in_a_heredoc_is_read_as_the_bare_patch(self):
        self.assertEqual(self.targets(fixture("codex-heredoc")), self.targets(fixture("codex-write")))

    def test_a_shell_command_is_not_judged(self):
        self.assertEqual(self.targets(fixture("codex-read")), [])

    def test_a_moved_file_is_judged_at_its_destination_from_its_source(self):
        event = codex_event(patch("*** Update File: a.py", "*** Move to: b.py", "@@", "-x", "+y"))
        source = at_repo("a.py")
        self.assertEqual(self.targets(event), [hook.Target("CodexPatch", at_repo("b.py"),
                                                           {"file_path": source, "hunks": [hunk(["x"], ["y"])]},
                                                           True, source)])

    def test_every_file_of_a_patch_is_a_target_in_order(self):
        event = codex_event(patch("*** Add File: a.py", "+a", "*** Delete File: b.py", "*** Update File: c.py",
                                  "@@", "-c", "+d"))
        self.assertEqual([(found.tool, found.path) for found in self.targets(event)],
                         [("Write", at_repo("a.py")), ("CodexPatch", at_repo("c.py"))])

    def test_two_operations_on_one_path_are_refused(self):
        for lines in (("*** Update File: a.py", "*** Move to: b.py", "@@", "+x", "*** Update File: b.py", "@@", "+y"),
                      ("*** Update File: a.py", "*** Move to: ./b.py", "@@", "+x", "*** Update File: b.py", "@@", "+y"),
                      ("*** Update File: a.py", "@@", "+x", "*** Update File: ./a.py", "@@", "+y"),
                      ("*** Add File: a.py", "+x", "*** Update File: a.py", "@@", "+y"),
                      ("*** Add File: a.py", "+x", "*** Delete File: a.py"),
                      ("*** Delete File: a.py", "*** Add File: a.py", "+x")):
            with self.subTest(lines=lines):
                with self.assertRaises(hook.HookInputError):
                    self.targets(codex_event(patch(*lines)))

    def test_a_moved_file_may_be_added_or_deleted_later_as_codex_allows(self):
        moved = ("*** Update File: a.py", "*** Move to: b.py", "@@", "+x")
        self.assertEqual(len(self.targets(codex_event(patch(*moved + ("*** Add File: b.py", "+y"))))), 2)
        self.assertEqual(len(self.targets(codex_event(patch(*moved + ("*** Delete File: b.py",))))), 1)

    def test_a_relative_path_resolves_against_the_event_cwd_only_when_it_is_a_string(self):
        for cwd, expected in (("/elsewhere", os.path.join("/elsewhere", "a.py")), ("", "a.py"), (None, "a.py"),
                              (7, "a.py")):
            with self.subTest(cwd=cwd):
                found = self.targets(codex_event(patch("*** Add File: a.py", "+a"), cwd=cwd))
                self.assertEqual([target.path for target in found], [expected])

    def test_an_absolute_path_is_kept(self):
        path = os.path.abspath(os.path.join(os.sep, "abs", "a.py"))
        found = self.targets(codex_event(patch("*** Add File: %s" % path, "+a")))
        self.assertEqual([target.path for target in found], [path])

    def test_a_patch_codex_would_refuse_is_not_the_event(self):
        for command in ("", "not a patch", patch("*** Update File: a.py"), 7):
            with self.subTest(command=command):
                with self.assertRaises(hook.HookInputError):
                    self.targets(codex_event(command))

    def test_an_event_with_no_tool_name_is_refused(self):
        event = fixture("codex-write")
        del event["tool_name"]
        with self.assertRaises(hook.HookInputError):
            self.targets(event)

    def test_a_patch_proposes_its_text_and_nothing_for_a_missing_file(self):
        target = hook.Target("CodexPatch", "a.py", {"file_path": "a.py", "hunks": [hunk(["x"], ["y"])]}, True)
        self.assertEqual(hook.proposed_text(target, "x\n"), "y\n")
        self.assertIsNone(hook.proposed_text(target, None))


class TestCodexPatchParser(unittest.TestCase):
    def parse(self, *lines):
        return hook.parse_codex_patch(patch(*lines))

    def assert_refused(self, text):
        with self.assertRaises(hook.HookInputError):
            hook.parse_codex_patch(text)

    def test_an_added_file_holds_its_plus_lines(self):
        self.assertEqual(self.parse("*** Add File: a.py", "+one", "+", "+two"),
                         [codex_patch.CodexFile("add", "a.py", None, "one\n\ntwo\n", None)])

    def test_an_updated_file_holds_its_hunks(self):
        self.assertEqual(self.parse("*** Update File: a.py", "@@ def f():", " keep", "-old", "+new", "@@", "-x", "+y"),
                         [codex_patch.CodexFile("update", "a.py", None, None, [
                             hunk(["keep", "old"], ["keep", "new"], anchor="def f():", context=((0, 0),)),
                             hunk(["x"], ["y"])])])

    def test_a_deleted_file_has_no_body(self):
        self.assertEqual(self.parse("*** Delete File: a.py"),
                         [codex_patch.CodexFile("delete", "a.py", None, None, None)])

    def test_a_moved_file_names_its_destination(self):
        self.assertEqual(self.parse("*** Update File: a.py", "*** Move to: b/c.py", "@@", "-x", "+y"),
                         [codex_patch.CodexFile("update", "a.py", "b/c.py", None, [hunk(["x"], ["y"])])])

    def test_a_bare_heredoc_around_the_patch_is_dropped(self):
        for opener in ("<<EOF", "<<'EOF'", '<<"EOF"'):
            with self.subTest(opener=opener):
                text = "%s\n%s\nEOF\n" % (opener, patch("*** Delete File: a.py"))
                self.assertEqual(hook.parse_codex_patch(text), self.parse("*** Delete File: a.py"))

    def test_a_heredoc_that_starts_with_a_command_is_refused(self):
        self.assert_refused("apply_patch <<'EOF'\n%s\nEOF\n" % patch("*** Delete File: a.py"))

    def test_an_environment_id_after_begin_patch_is_ignored(self):
        self.assertEqual(self.parse("*** Environment ID: remote", "*** Delete File: a.py"),
                         self.parse("*** Delete File: a.py"))

    def test_an_environment_id_that_is_empty_repeated_or_late_is_refused(self):
        for lines in (("*** Environment ID: ", "*** Delete File: a.py"),
                      ("*** Environment ID: a", "*** Environment ID: b", "*** Delete File: a.py"),
                      ("*** Delete File: a.py", "*** Environment ID: a")):
            with self.subTest(lines=lines):
                self.assert_refused(patch(*lines))

    def test_windows_line_endings_are_tolerated(self):
        text = patch("*** Update File: a.py", "@@", " keep", "-x", "+y").replace("\n", "\r\n")
        self.assertEqual(hook.parse_codex_patch(text), self.parse("*** Update File: a.py", "@@", " keep", "-x", "+y"))

    def test_markers_may_carry_surrounding_whitespace(self):
        text = "\n  *** Begin Patch  \n  *** Add File: a.py  \n+a\n  *** End Patch  \n\n"
        self.assertEqual(hook.parse_codex_patch(text), [codex_patch.CodexFile("add", "a.py", None, "a\n", None)])

    def test_a_first_chunk_may_omit_its_marker(self):
        self.assertEqual(self.parse("*** Update File: a.py", " keep", "-x", "+y"),
                         self.parse("*** Update File: a.py", "@@", " keep", "-x", "+y"))

    def test_an_empty_line_in_an_update_is_empty_context(self):
        found = hunk(["x", ""], ["", "y"], context=((1, 0),))
        self.assertEqual(self.parse("*** Update File: a.py", "@@", "-x", "", "+y"),
                         [codex_patch.CodexFile("update", "a.py", None, None, [found])])

    def test_end_of_file_marks_the_hunk_before_it(self):
        self.assertEqual(self.parse("*** Update File: a.py", "@@", "-x", "+y", "*** End of File", "", "@@", "+z"),
                         [codex_patch.CodexFile("update", "a.py", None, None, [hunk(["x"], ["y"], at_end=True),
                                                                               hunk([], ["z"])])])

    def test_an_empty_patch_has_no_files(self):
        self.assertEqual(self.parse(), [])

    def test_text_codex_refuses_is_refused(self):
        for text in ("", "not a patch", "*** Begin Patch\n*** Add File: a.py\n+x",
                     patch("*** Update File: a.py"),
                     patch("*** Update File: a.py", "@@", "@@", "-x"),
                     patch("*** Update File: a.py", "@@"),
                     patch("*** Update File: a.py", "@@", "*** End of File"),
                     patch("*** Update File: a.py", "@@", "-x", "*** End of File", " y"),
                     patch("*** Update File: a.py", "-x", "garbage"),
                     patch("*** Update File: a.py", "@@", "-x", "*** Move to: b.py"),
                     patch("*** Add File: a.py", "x"),
                     patch("*** Delete File: a.py", "+x"),
                     patch("*** Frobnicate: a.py"),
                     "*** Begin Patch\n*** End Patch\nmore\n*** End Patch"):
            with self.subTest(text=text):
                self.assert_refused(text)


class TestCodexHunks(unittest.TestCase):
    def apply(self, text, *hunks):
        return hook.apply_codex_hunks(text, list(hunks))

    def test_old_lines_are_replaced_by_new_lines(self):
        self.assertEqual(self.apply("a\nb\nc\n", hunk(["b"], ["x", "y"])), "a\nx\ny\nc\n")

    def test_an_anchor_moves_the_search_past_it(self):
        text = "def a():\n    return 1\ndef b():\n    return 1\n"
        self.assertEqual(self.apply(text, hunk(["    return 1"], ["    return 2"], anchor="def b():")),
                         "def a():\n    return 1\ndef b():\n    return 2\n")

    def test_an_anchor_that_is_not_found_does_not_apply(self):
        self.assertIsNone(self.apply("a\n", hunk(["a"], ["b"], anchor="def c():")))

    def test_an_exact_match_wins_over_one_that_ignores_whitespace(self):
        self.assertEqual(self.apply("x \nx\n", hunk(["x"], ["y"])), "x \ny\n")

    def test_trailing_whitespace_is_ignored_before_leading_whitespace(self):
        self.assertEqual(self.apply("  x\nx  \n", hunk(["x"], ["y"])), "  x\ny\n")

    def test_leading_whitespace_is_ignored_last_of_the_three(self):
        self.assertEqual(self.apply("a\n  x\n", hunk(["x"], ["y"])), "a\ny\n")

    def test_unicode_punctuation_matches_its_ascii_form_last(self):
        text = "a \u2013 \u201cb\u201d\u00a0\u2019c\u2019\n"
        self.assertEqual(self.apply(text, hunk(["a - \"b\" 'c'"], ["d"])), "d\n")

    def test_a_context_line_keeps_the_line_ending_of_the_file(self):
        self.assertEqual(self.apply("keep\r\nold\n", hunk(["keep", "old"], ["keep", "new"], context=((0, 0),))),
                         "keep\r\nnew\r\n")

    def test_a_context_line_matched_loosely_does_not_apply(self):
        self.assertIsNone(self.apply("    keep  \nold\n", hunk(["keep", "old"], ["keep", "new"], context=((0, 0),))))

    def test_insertions_older_releases_put_in_another_order_do_not_apply(self):
        self.assertIsNone(self.apply("x\n# a\n", hunk([], ["y"]), hunk(["# a"], ["# a", "# b"], context=((0, 0),))))

    def test_an_end_of_file_hunk_matches_at_the_end(self):
        self.assertEqual(self.apply("x\ny\nx\n", hunk(["x"], ["z"], at_end=True)), "x\ny\nz\n")
        self.assertEqual(self.apply("x\ny\nx\n", hunk(["x"], ["z"])), "z\ny\nx\n")

    def test_an_end_of_file_hunk_that_is_not_at_the_end_does_not_apply(self):
        self.assertIsNone(self.apply("x\ny\n", hunk(["x"], ["z"], at_end=True)))

    def test_a_trailing_empty_old_line_is_retried_without_it(self):
        self.assertEqual(self.apply("a\n", hunk(["a", ""], ["b", ""])), "b\n")

    def test_a_hunk_with_no_old_lines_is_appended_at_the_end(self):
        self.assertEqual(self.apply("a\nb\n", hunk([], ["c"], anchor="a")), "a\nb\nc\n")

    def test_hunks_apply_in_order_each_after_the_last(self):
        self.assertEqual(self.apply("a\nb\na\n", hunk(["a"], ["x"]), hunk(["a"], ["y"])), "x\nb\ny\n")

    def test_a_hunk_before_the_last_match_does_not_apply(self):
        self.assertIsNone(self.apply("a\nb\n", hunk(["b"], ["y"]), hunk(["a"], ["x"])))

    def test_old_lines_that_match_nothing_do_not_apply(self):
        self.assertIsNone(self.apply("a\nb\n", hunk(["c"], ["d"])))

    def test_old_lines_longer_than_the_file_do_not_apply(self):
        self.assertIsNone(self.apply("a\n", hunk(["a", "b"], ["c"])))

    def test_the_file_keeps_its_line_endings_and_new_lines_take_the_first(self):
        self.assertEqual(self.apply("a\r\nb\nc\r", hunk(["a"], ["x", "y"])), "x\r\ny\r\nb\nc\r")

    def test_every_line_ends_with_a_newline_afterwards(self):
        self.assertEqual(self.apply("a\nb", hunk(["a"], ["x"])), "x\nb\n")


class TestCodexReleases(unittest.TestCase):
    """The text each Codex release writes: 0.162.0 and later preserve line endings, earlier ones normalize to LF."""

    def both(self, text, *hunks):
        return tuple(codex_patch.applied(text, list(hunks), preserve) for preserve in (True, False))

    def test_a_pure_addition_and_an_insertion_at_the_end_come_out_in_another_order(self):
        hunks = (hunk([], ["y = 1"]), hunk(["# old"], ["# old", "# new"], context=((0, 0),)))
        self.assertEqual(self.both("x = 0\n# old\n", *hunks),
                         ("x = 0\n# old\ny = 1\n# new\n", "x = 0\n# old\n# new\ny = 1\n"))

    def test_only_later_releases_keep_the_text_of_a_context_line_matched_loosely(self):
        self.assertEqual(self.both("    keep  \nold\n", hunk(["keep", "old"], ["keep", "new"], context=((0, 0),))),
                         ("    keep  \nnew\n", "keep\nnew\n"))

    def test_only_later_releases_end_a_line_at_a_lone_carriage_return(self):
        found = hunk(["a\rb", "y"], ["a\rb", "z"], context=((0, 0),))
        self.assertEqual(self.both("a\rb\ny\n", found), (None, "a\rb\nz\n"))

    def test_only_later_releases_keep_the_ending_of_a_line_they_write(self):
        self.assertEqual(self.both("a\r\nb\r\n", hunk(["a"], ["x"])), ("x\r\nb\r\n", "x\nb\r\n"))

    def test_earlier_releases_add_a_pure_addition_before_a_final_empty_line(self):
        self.assertEqual(self.both("a\n\n", hunk([], ["b"])), ("a\n\nb\n", "a\nb\n"))

    def test_earlier_releases_seek_an_end_of_file_hunk_from_the_end_alone(self):
        self.assertEqual(self.both("a\nb\n", hunk(["b"], ["c"]), hunk(["b"], ["d"], at_end=True)), (None, "a\nc\n"))

    def test_a_patch_both_releases_write_alike_applies(self):
        self.assertEqual(hook.apply_codex_hunks("a\r\nb\r\n", [hunk(["a"], ["x"])]), "x\r\nb\r\n")


class TestWindsurfAdapter(AdapterContract, unittest.TestCase):
    agent, write_fixture, non_write_fixture, pathless_fixture = (
        "windsurf", "windsurf-write", "windsurf-read", "windsurf-pathless")

    def test_the_edit_fixture_is_one_multiedit_that_must_apply(self):
        event = fixture("windsurf-edit")
        path, edits = event["tool_info"]["file_path"], event["tool_info"]["edits"]
        self.assertEqual(hook.targets(event, "windsurf"),
                         [hook.Target("MultiEdit", path, {"file_path": path, "edits": edits}, must_apply=True)])

    def test_the_write_fixture_is_an_edit_with_an_empty_old_string(self):
        (found,) = hook.targets(fixture("windsurf-write"), "windsurf")
        self.assertEqual(found.tool_input["edits"][0]["old_string"], "")
        self.assertEqual(hook.proposed_text(found, None), found.tool_input["edits"][0]["new_string"])

    def test_another_action_is_not_judged(self):
        self.assertEqual(hook.targets(dict(fixture("windsurf-edit"), agent_action_name="post_write_code"),
                                      "windsurf"), [])

    def test_an_event_without_an_action_name_is_refused(self):
        for name in (None, 3):
            event = dict(fixture("windsurf-edit"), agent_action_name=name)
            with self.subTest(name=name), self.assertRaises(hook.HookInputError):
                hook.targets(event, "windsurf")
        event = fixture("windsurf-edit")
        del event["agent_action_name"]
        with self.assertRaises(hook.HookInputError):
            hook.targets(event, "windsurf")

    def test_a_bad_path_or_edits_is_refused(self):
        for info in ({"file_path": "", "edits": []}, {"file_path": 3, "edits": []}, {"edits": []},
                     {"file_path": "a.py", "edits": "x"}, {"file_path": "a.py"}, "x"):
            event = dict(fixture("windsurf-edit"), tool_info=info)
            with self.subTest(info=info), self.assertRaises(hook.HookInputError):
                hook.targets(event, "windsurf")


class TestGeminiAdapter(AdapterContract, unittest.TestCase):
    agent, write_fixture, non_write_fixture, pathless_fixture = (
        "gemini", "gemini-write", "gemini-read", "gemini-pathless")

    def test_the_write_fixture_is_a_write(self):
        event = fixture("gemini-write")
        info = event["tool_input"]
        self.assertEqual(hook.targets(event, "gemini"),
                         [hook.Target("Write", info["file_path"],
                                      {"file_path": info["file_path"], "content": info["content"]})])

    def test_the_edit_fixture_is_an_edit_that_must_apply_and_ignores_the_instruction(self):
        event = fixture("gemini-edit")
        info = event["tool_input"]
        expected = {"file_path": info["file_path"], "old_string": info["old_string"],
                    "new_string": info["new_string"], "replace_all": False}
        self.assertEqual(hook.targets(event, "gemini"),
                         [hook.Target("Edit", info["file_path"], expected, must_apply=True)])

    def test_allow_multiple_becomes_replace_all_and_defaults_to_false(self):
        event = fixture("gemini-edit")
        event["tool_input"]["allow_multiple"] = True
        self.assertTrue(hook.targets(event, "gemini")[0].tool_input["replace_all"])
        del event["tool_input"]["allow_multiple"]
        self.assertFalse(hook.targets(event, "gemini")[0].tool_input["replace_all"])

    def test_a_non_boolean_allow_multiple_is_refused(self):
        event = fixture("gemini-edit")
        event["tool_input"]["allow_multiple"] = "yes"
        with self.assertRaises(hook.HookInputError):
            hook.targets(event, "gemini")

    def test_a_relative_path_resolves_against_the_events_cwd(self):
        for name in ("gemini-write", "gemini-edit"):
            event = fixture(name)
            event["tool_input"]["file_path"] = "src/a.py"
            (found,) = hook.targets(event, "gemini")
            self.assertEqual((found.path, found.tool_input["file_path"]), (at_repo("src/a.py"),) * 2)

    def test_another_event_is_not_judged_and_a_missing_one_is_refused(self):
        self.assertEqual(hook.targets(dict(fixture("gemini-edit"), hook_event_name="AfterTool"), "gemini"), [])
        for name in (None, 3):
            with self.subTest(name=name), self.assertRaises(hook.HookInputError):
                hook.targets(dict(fixture("gemini-edit"), hook_event_name=name), "gemini")
        event = fixture("gemini-edit")
        del event["hook_event_name"]
        with self.assertRaises(hook.HookInputError):
            hook.targets(event, "gemini")

    def test_a_missing_tool_name_is_refused(self):
        with self.assertRaises(hook.HookInputError):
            hook.targets(dict(fixture("gemini-edit"), tool_name=None), "gemini")

    def test_a_bad_path_is_refused_for_both_tools(self):
        for name in ("gemini-write", "gemini-edit"):
            for path in ("", 3, None):
                event = fixture(name)
                event["tool_input"]["file_path"] = path
                with self.subTest(name=name, path=path), self.assertRaises(hook.HookInputError):
                    hook.targets(event, "gemini")
