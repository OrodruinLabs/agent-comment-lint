"""The command line end to end: modes, exit codes, settings, and the could-not-scan paths."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from unittest import mock

from agent_comment_lint import __version__, cli, gitio, hook, report, session
from test_agents import fixture

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TWO_BLOCKS = "// one\n// two\nint x;\n// three\n// four\n"
CLEAN_ONE = "agent-comment-lint: clean, 1 file(s) scanned.\n"
CLEAN_NONE = "agent-comment-lint: clean, 0 file(s) scanned.\n"


def event(tool, path, **tool_input):
    """A PreToolUse event as Claude Code sends it on standard input."""
    return json.dumps({"tool_name": tool, "tool_input": dict(tool_input, file_path=path)})


class Sandbox(unittest.TestCase):
    """A throwaway directory outside any work tree; `run` calls the command line in process."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, name, content):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def write_bytes(self, name, content):
        self.write(name, "")
        with open(os.path.join(self.tmp, name), "wb") as handle:
            handle.write(content)

    def run_cli(self, *args, stdin="", cwd=None):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(args), stdin=io.StringIO(stdin), stdout=out, stderr=err, cwd=cwd or self.tmp)
        return code, out.getvalue(), err.getvalue()

    def git(self, *args):
        return subprocess.run(("git",) + args, cwd=self.tmp, capture_output=True, text=True, check=True)

    def init_repo(self):
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def make_executable(self, name):
        os.chmod(os.path.join(self.tmp, name), 0o755)
        # Git on Windows ignores the executable bit on disk, so the mode change is recorded in the index directly.
        self.git("update-index", "--chmod=+x", name)


class TestUsage(Sandbox):
    def assert_usage_error(self, *args):
        with self.assertRaises(SystemExit) as caught:
            with open(os.devnull, "w") as quiet:
                stderr, sys.stderr = sys.stderr, quiet
                try:
                    cli.main(list(args), cwd=self.tmp)
                finally:
                    sys.stderr = stderr
        self.assertEqual(caught.exception.code, 2)

    def test_no_mode_is_a_usage_error(self):
        self.assert_usage_error()

    def test_agent_without_hook_is_a_usage_error(self):
        self.assert_usage_error("--agent", "claude", "--all")

    def test_an_unknown_agent_is_a_usage_error(self):
        self.assert_usage_error("--hook", "--agent", "nope")

    def test_files_with_no_paths_is_a_usage_error(self):
        self.assert_usage_error("--files")

    def test_two_modes_at_once_is_a_usage_error(self):
        self.assert_usage_error("--all", "--diff", "HEAD")

    def test_an_unknown_option_is_a_usage_error(self):
        self.assert_usage_error("--all", "--every-block")

    def test_json_with_hook_is_a_usage_error(self):
        self.assert_usage_error("--hook", "--json")

    def test_the_hook_help_names_the_three_events_it_reads(self):
        out = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(out):
            cli.main(["--help"], cwd=self.tmp)
        help_text = " ".join(out.getvalue().split())
        for name in ("PreToolUse", "SessionStart", "Stop"):
            self.assertIn(name, help_text)


class TestFilesMode(Sandbox):
    def test_a_clean_file_exits_zero(self):
        self.write("Clean.cs", "public int X => 1;\n")
        self.assertEqual(self.run_cli("--files", "Clean.cs"),
                         (0, "agent-comment-lint: clean, 1 file(s) scanned.\n", ""))

    def test_a_violating_file_exits_one_and_prints_path_line_rule_message(self):
        self.write("src/Dirty.cs", "/// prose one\n/// prose two\n")
        code, out, _err = self.run_cli("--files", "src/Dirty.cs")
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[0], "src/Dirty.cs:1: C1: 2-line prose block (limit 1)")

    def test_every_block_is_scored_not_only_the_worst(self):
        self.write("Two.cs", TWO_BLOCKS)
        _code, out, _err = self.run_cli("--files", "Two.cs")
        self.assertEqual([line.split(": ")[0] for line in out.splitlines()[:2]], ["Two.cs:1", "Two.cs:4"])

    def test_a_directory_is_refused_rather_than_reported_clean(self):
        os.makedirs(os.path.join(self.tmp, "scripts"))
        code, out, err = self.run_cli("--files", "scripts")
        self.assertEqual(code, 2)
        self.assertIn("scripts: could not scan: is a directory", err)
        self.assertNotIn("clean", out)

    def test_a_missing_file_is_refused(self):
        code, out, err = self.run_cli("--files", "does/not/exist.cs")
        self.assertEqual(code, 2)
        self.assertIn("does/not/exist.cs: could not scan:", err)
        self.assertNotIn("clean", out)

    def test_a_path_outside_the_root_is_refused(self):
        code, _out, err = self.run_cli("--files", "../outside.cs")
        self.assertEqual(code, 2)
        self.assertIn("resolves outside the repository root", err)

    def test_a_path_that_shares_no_part_with_the_root_is_refused(self):
        self.write("a.cs", "int x;\n")
        with mock.patch.object(cli.os.path, "commonpath", side_effect=ValueError("paths on two drives")):
            code, out, err = self.run_cli("--files", "a.cs")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("a.cs: could not scan: resolves outside the repository root", err)

    def test_a_file_that_cannot_be_lexed_exits_two_with_its_line(self):
        self.write("a.ts", "const a = 1;\nconst t = `never closes\n")
        self.write("b.ts", "// one\n// two\n")
        code, out, err = self.run_cli("--files", "a.ts", "b.ts")
        self.assertEqual(code, 2)
        self.assertIn("a.ts:2: could not scan: unterminated template literal", err)
        self.assertIn("b.ts:1: C1", out)
        self.assertNotIn("clean", out)

    def test_a_byte_order_mark_does_not_hide_the_first_line(self):
        self.write("Marked.cs", "\ufeff// one\n// two\n")
        self.write("marked.py", '\ufeff"""One.\nTwo."""\n')
        code, out, _err = self.run_cli("--files", "Marked.cs", "marked.py")
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[:-1], ["Marked.cs:1: C1: 2-line prose block (limit 1)",
                                                 "marked.py:1: C1: 2-line prose block (limit 1)"])

    def test_bytes_that_are_not_utf_8_do_not_stop_a_named_file_or_a_whole_tree(self):
        with open(os.path.join(self.tmp, "Latin.cs"), "wb") as handle:
            handle.write("// caf\u00e9 one\n// two\n".encode("latin-1"))
        for mode in (["--files", "Latin.cs"], ["--all"]):
            code, out, err = self.run_cli(*mode)
            self.assertEqual((code, out.splitlines()[0], err), (1, "Latin.cs:1: C1: 2-line prose block (limit 1)", ""))

    def test_a_file_named_twice_is_judged_once(self):
        self.write("Dirty.cs", "// one\n// two\n")
        code, out, _err = self.run_cli("--files", "Dirty.cs", "./Dirty.cs")
        self.assertEqual((code, out.splitlines()[-1]),
                         (1, "agent-comment-lint: 1 violation(s) in 1 of 1 file(s) scanned."))

    def test_a_named_file_outside_the_scope_is_not_judged(self):
        self.write("notes.md", "// one\n// two\n")
        self.assertEqual(self.run_cli("--files", "notes.md")[:2],
                         (0, "agent-comment-lint: clean, 0 file(s) scanned.\n"))

    def test_paths_are_reported_relative_to_the_root_from_any_directory(self):
        self.init_repo()
        self.write("src/deep/Dirty.cs", "// see ADR-0001\n")
        code, out, _err = self.run_cli("--files", "Dirty.cs", cwd=os.path.join(self.tmp, "src", "deep"))
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("src/deep/Dirty.cs:1: C3:"), out)


    def test_the_file_system_root_is_a_root_like_any_other(self):
        self.write("src/Dirty.cs", "// see ADR-0001\n")
        named = os.path.join(self.tmp, "src", "Dirty.cs")
        top = os.path.splitdrive(self.tmp)[0] + os.sep
        for mode in (["--files", named], ["--stdin-path", named]):
            code, out, err = self.run_cli(*mode, "--root", os.sep, stdin="// see ADR-0001\n")
            self.assertEqual((code, err), (1, ""), mode)
            self.assertEqual(out.splitlines()[0], "%s:1: C3: governance reference 'ADR-0001'"
                             % os.path.relpath(named, top).replace(os.sep, "/"), mode)


class TestAllMode(Sandbox):
    def test_a_tree_outside_git_is_walked(self):
        self.write("src/Dirty.cs", TWO_BLOCKS)
        self.write("src/Clean.cs", "public int X => 1;\n")
        code, out, _err = self.run_cli("--all")
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["src/Dirty.cs:1: C1: 2-line prose block (limit 1)",
                                            "src/Dirty.cs:4: C1: 2-line prose block (limit 1)",
                                            "agent-comment-lint: 2 violation(s) in 1 of 2 file(s) scanned."])

    def test_a_clean_tree_exits_zero(self):
        self.write("Clean.cs", "public int X => 1;\n")
        self.assertEqual(self.run_cli("--all")[0], 0)

    def test_every_covered_language_reports_a_planted_violation(self):
        planted = {"a.cs": "// one\n// two\n", "a.ts": "// one\n// two\n", "a.tsx": "// one\n// two\n",
                   "a.js": "// one\n// two\n", "a.jsx": "// one\n// two\n", "a.mjs": "// one\n// two\n",
                   "a.cjs": "// one\n// two\n", "a.mts": "// one\n// two\n", "a.cts": "// one\n// two\n",
                   "a.css": "/* one\n   two */\n", "a.sh": "#!/bin/sh\n# one\n# two\n", "a.yml": "# one\n# two\n",
                   "a.yaml": "# one\n# two\n", "a.tf": "# one\n# two\n", "a.tfvars": "# one\n# two\n",
                   "a.hcl": "# one\n# two\n", "a.py": 'def f():\n    """One.\n    Two."""\n'}
        for name, text in planted.items():
            self.write(name, text)
        code, out, _err = self.run_cli("--all")
        self.assertEqual(code, 1)
        reported = sorted(line.split(":")[0] for line in out.splitlines()[:-1])
        self.assertEqual(reported, sorted(planted))

    def test_default_skips_are_not_judged(self):
        self.write(".venv/lib/vendored.py", '"""One.\nTwo."""\n')
        self.write("node_modules/pkg/index.js", "// one\n// two\n")
        self.write("stacks/.terraform.lock.hcl", "# one\n# two\n")
        self.write("src/Clean.cs", "public int X => 1;\n")
        self.assertEqual(self.run_cli("--all")[:2], (0, "agent-comment-lint: clean, 1 file(s) scanned.\n"))

    def test_a_tree_with_no_covered_file_is_no_verdict(self):
        self.write("notes.md", "// one\n// two\n")
        self.write("node_modules/pkg/index.js", "// one\n// two\n")
        code, out, err = self.run_cli("--all")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--all: could not scan: no covered file under the root", err)

    def test_a_tree_whose_covered_files_are_all_excluded_is_no_verdict(self):
        self.write("public/worker.js", "// one\n// two\n")
        self.write(".agent-comment-lint.json", '{"exclude": [{"path": "public/", "reason": "generated"}]}')
        self.assertEqual(self.run_cli("--all")[0], 2)

    def test_a_root_that_does_not_exist_is_refused(self):
        self.write("Clean.cs", "public int X => 1;\n")
        for mode in (["--all"], ["--files", "Clean.cs"], ["--stdin-path", "Clean.cs"]):
            code, out, err = self.run_cli(*mode, "--root", "no/such/dir")
            self.assertEqual((code, out), (2, ""), mode)
            self.assertIn("--root: could not scan: no/such/dir is not a directory", err)

    def test_a_root_that_is_a_file_is_refused(self):
        self.write("Clean.cs", "public int X => 1;\n")
        code, _out, err = self.run_cli("--all", "--root", "Clean.cs")
        self.assertEqual(code, 2)
        self.assertIn("--root: could not scan: Clean.cs is not a directory", err)

    def test_a_root_outside_git_is_walked(self):
        self.write("tree/Dirty.cs", "// one\n// two\n")
        code, out, _err = self.run_cli("--all", "--root", "tree")
        self.assertEqual((code, out.splitlines()[0]), (1, "Dirty.cs:1: C1: 2-line prose block (limit 1)"))

    def test_the_run_is_deterministic(self):
        for name in ("b/z.cs", "a/y.ts", "c.py"):
            self.write(name, "# one\n# two\n" if name.endswith(".py") else "// one\n// two\n")
        first = self.run_cli("--all")
        self.assertEqual(first, self.run_cli("--all"))
        self.assertEqual([line.split(":")[0] for line in first[1].splitlines()[:-1]], ["a/y.ts", "b/z.cs", "c.py"])


class TestAllModeInsideGit(Sandbox):
    def test_tracked_and_new_files_are_scored_but_not_ignored_ones(self):
        self.init_repo()
        self.write(".gitignore", "ignored/\n")
        self.write("Tracked.cs", "/// one\n/// two\n")
        self.commit("base")
        self.write("ignored/Dirty.cs", "/// one\n/// two\n")
        self.write("New.cs", "/// one\n/// two\n")
        code, out, _err = self.run_cli("--all")
        self.assertEqual(code, 1)
        self.assertIn("Tracked.cs:1: C1", out)
        self.assertIn("New.cs:1: C1", out)
        self.assertNotIn("Dirty.cs", out)

    def test_a_repository_git_cannot_read_is_no_verdict_and_is_not_walked(self):
        self.write("Dirty.cs", "// one\n// two\n")
        self.write(".git", "gitdir: /no/such/repository\n")
        for mode in (["--all"], ["--all", "--root", "."]):
            code, out, err = self.run_cli(*mode)
            self.assertEqual((code, out), (2, ""), mode)
            self.assertIn("git: could not scan: git rev-parse failed:", err)

    def test_a_repository_without_a_git_program_is_no_verdict_and_is_not_walked(self):
        self.init_repo()
        self.write("Dirty.cs", "// one\n// two\n")
        with mock.patch.object(gitio.subprocess, "run", side_effect=FileNotFoundError(2, "No such file or directory")):
            code, out, err = self.run_cli("--all")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("git: could not scan: git could not be run", err)

    def test_a_subdirectory_of_a_repository_is_listed_by_git(self):
        self.init_repo()
        self.write(".gitignore", "ignored/\n")
        self.write("src/ignored/Dirty.cs", "// one\n// two\n")
        self.write("src/Kept.cs", "// one\n// two\n")
        code, out, _err = self.run_cli("--all", cwd=os.path.join(self.tmp, "src"))
        self.assertEqual((code, out.splitlines()[0]), (1, "src/Kept.cs:1: C1: 2-line prose block (limit 1)"))
        self.assertNotIn("Dirty.cs", out)


class TestGitThatCannotAnswer(Sandbox):
    """Only --all and --diff need git; a named file and standard input get their verdict without it."""

    DIRTY = "// one\n// two\n"
    FOUND = "a.cs:1: C1: 2-line prose block (limit 1)"

    def assert_named_text_is_judged(self, *options, cwd=None):
        for mode in (["--files", "a.cs"], ["--stdin-path", "a.cs"]):
            code, out, err = self.run_cli(*mode, *options, stdin=self.DIRTY, cwd=cwd)
            self.assertEqual((code, out.splitlines()[0], err), (1, self.FOUND, ""), mode)

    def assert_no_verdict(self, *mode, cwd=None):
        code, out, err = self.run_cli(*mode, cwd=cwd)
        self.assertEqual((code, out), (2, ""), mode)
        self.assertIn("git: could not scan: git ", err)
        self.assertNotIn("does not resolve", err)

    def without_a_git_program(self):
        os.makedirs(os.path.join(self.tmp, "no-programs"))
        return mock.patch.dict(os.environ, {"PATH": os.path.join(self.tmp, "no-programs")})

    def test_a_git_directory_named_in_the_environment_that_does_not_exist(self):
        self.write("a.cs", self.DIRTY)
        with mock.patch.dict(os.environ, {"GIT_DIR": os.path.join(self.tmp, "no", "such")}):
            self.assert_named_text_is_judged()
            self.assert_no_verdict("--all")
            self.assert_no_verdict("--diff", "HEAD")

    def test_a_stale_git_file_in_a_parent_directory(self):
        self.write(".git", "gitdir: /no/such/repository\n")
        self.write("sub/a.cs", self.DIRTY)
        inside = os.path.join(self.tmp, "sub")
        self.assert_named_text_is_judged(cwd=inside)
        self.assert_no_verdict("--all", cwd=inside)
        self.assert_no_verdict("--diff", "HEAD", cwd=inside)

    def test_a_repository_without_a_git_program(self):
        self.init_repo()
        self.write("a.cs", self.DIRTY)
        self.commit("base")
        with self.without_a_git_program():
            self.assert_named_text_is_judged()
            self.assert_no_verdict("--all")
            self.assert_no_verdict("--diff", "HEAD")

    def test_no_repository_and_no_git_program(self):
        self.write("a.cs", self.DIRTY)
        with self.without_a_git_program():
            self.assert_named_text_is_judged()
            self.assertEqual(self.run_cli("--all")[:2], (1, self.FOUND + "\nagent-comment-lint: 1 violation(s) in 1 "
                                                         "of 1 file(s) scanned.\n"))
            self.assert_no_verdict("--diff", "HEAD")

    def test_a_named_root_is_used_without_asking_git(self):
        self.write("tree/a.cs", self.DIRTY)
        with mock.patch.object(gitio, "_git", side_effect=AssertionError("git was asked")):
            self.assert_named_text_is_judged("--root", ".", cwd=os.path.join(self.tmp, "tree"))

    def test_a_root_that_is_not_a_directory_is_refused_in_the_modes_that_need_git(self):
        self.init_repo()
        self.write("a.cs", self.DIRTY)
        self.commit("base")
        for mode in (["--all"], ["--diff", "HEAD"]):
            code, out, err = self.run_cli(*mode, "--root", "a.cs")
            self.assertEqual((code, out), (2, ""), mode)
            self.assertIn("--root: could not scan: a.cs is not a directory", err)


class TestSettings(Sandbox):
    def setUp(self):
        super().setUp()
        self.write("public/worker.js", "// one\n// two\n")
        self.write("docs/design/a.css", "/* one\n   two */\n")
        self.write("src/a.ts", "const a = 1;\n")

    def exclude(self, *paths):
        entries = [{"path": path, "reason": "not authored here"} for path in paths]
        self.write(".agent-comment-lint.json", json.dumps({"exclude": entries}))

    def test_without_settings_every_covered_file_is_judged(self):
        code, out, _err = self.run_cli("--all")
        self.assertEqual((code, out.splitlines()[-1]),
                         (1, "agent-comment-lint: 2 violation(s) in 2 of 3 file(s) scanned."))

    def test_excluded_paths_are_not_judged_in_any_mode(self):
        self.exclude("public/worker.js", "docs/design/")
        self.assertEqual(self.run_cli("--all")[:2], (0, "agent-comment-lint: clean, 1 file(s) scanned.\n"))
        self.assertEqual(self.run_cli("--files", "public/worker.js")[:2],
                         (0, "agent-comment-lint: clean, 0 file(s) scanned.\n"))
        self.assertEqual(self.run_cli("--stdin-path", "docs/design/a.css", stdin="/* one\n   two */\n")[0], 0)

    def test_a_byte_order_mark_in_the_settings_file_is_not_malformed_json(self):
        self.exclude("public/worker.js", "docs/design/")
        with open(os.path.join(self.tmp, ".agent-comment-lint.json"), encoding="utf-8") as handle:
            settings = handle.read()
        self.write(".agent-comment-lint.json", "\ufeff" + settings)
        self.assertEqual(self.run_cli("--all")[:2], (0, "agent-comment-lint: clean, 1 file(s) scanned.\n"))

    def test_malformed_settings_exit_two(self):
        self.write(".agent-comment-lint.json", '{"exclude": [{"path": "public/worker.js"}]}')
        code, out, err = self.run_cli("--all")
        self.assertEqual(code, 2)
        self.assertIn(".agent-comment-lint.json: could not scan:", err)
        self.assertNotIn("clean", out)

    def test_a_named_settings_file_that_is_missing_exits_two(self):
        code, _out, err = self.run_cli("--all", "--config", "missing.json")
        self.assertEqual(code, 2)
        self.assertIn("missing.json: could not scan:", err)

    def test_a_named_settings_file_replaces_the_default(self):
        self.write("ci/policy.json", json.dumps({"exclude": [{"path": "**/*.js", "reason": "why"},
                                                             {"path": "docs/**", "reason": "why"}]}))
        self.assertEqual(self.run_cli("--all", "--config", "ci/policy.json")[0], 0)


class TestGovernanceSettings(Sandbox):
    SETTINGS = {"governance": {"packs": ["azure-boards"],
                               "extra": [{"pattern": r"\bWEB-\d+", "reason": "the web team's tickets"}]}}

    def setUp(self):
        super().setUp()
        self.write("a.ts", "// see AB#4321\nconst a = 1;\n// fixed in WEB-12\n")

    def test_without_settings_pack_and_extra_shapes_pass(self):
        self.assertEqual(self.run_cli("--all")[:2], (0, CLEAN_ONE))

    def test_a_pack_and_an_extra_are_judged_in_every_mode(self):
        self.write(".agent-comment-lint.json", json.dumps(self.SETTINGS))
        expected = "a.ts:1: C3: governance reference 'AB#4321'\na.ts:3: C3: governance reference 'WEB-12'\n"
        for args in (("--all",), ("--files", "a.ts")):
            code, out, _err = self.run_cli(*args)
            self.assertEqual(code, 1, args)
            self.assertTrue(out.startswith(expected), out)
        self.assertEqual(self.run_cli("--stdin-path", "b.ts", stdin="// WEB-3\n")[0], 1)

    def test_the_hook_judges_with_the_settings_of_the_root(self):
        self.write(".agent-comment-lint.json", json.dumps(self.SETTINGS))
        code, _out, err = self.run_cli("--hook", stdin=event("Write", "b.ts", content="// fixed in WEB-12\n"))
        self.assertEqual(code, 2)
        self.assertIn("b.ts:1: C3: governance reference 'WEB-12'", err)

    def test_a_malformed_pattern_exits_two(self):
        self.write(".agent-comment-lint.json", json.dumps({"governance": {"extra": [{"pattern": "(", "reason": "x"}]}}))
        code, _out, err = self.run_cli("--all")
        self.assertEqual(code, 2)
        self.assertIn(".agent-comment-lint.json: could not scan:", err)


class TestDiffMode(Sandbox):
    def setUp(self):
        super().setUp()
        self.init_repo()

    def test_a_violation_on_an_added_line_is_reported_but_not_an_untouched_one(self):
        self.write("Sample.cs", "// see ADR-0001\npublic int X;\n// see ADR-0002\npublic int Y;\n")
        base = self.commit("base")
        self.write("Sample.cs", "// see ADR-0001\npublic int X;\n// see ADR-0002\npublic int Y;\n// see ADR-0003\n")
        self.commit("add a line")
        code, out, _err = self.run_cli("--diff", base)
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[0], "Sample.cs:5: C3: governance reference 'ADR-0003'")
        self.assertEqual(len(out.splitlines()), 2)

    def test_clean_when_only_untouched_lines_violate(self):
        self.write("Sample.cs", "// see ADR-0001\npublic int X;\n")
        base = self.commit("base")
        self.write("Sample.cs", "// see ADR-0001\npublic int Y;\n")
        self.commit("touch an unrelated line")
        self.assertEqual(self.run_cli("--diff", base)[0], 0)

    def test_a_block_that_starts_before_the_change_and_runs_into_it_is_reported(self):
        self.write("Sample.cs", "/// prose one\n/// prose two\n/// prose three\npublic void X() {}\n")
        base = self.commit("base")
        self.write("Sample.cs", "/// prose one\n/// prose two\n/// prose inserted\n/// prose three\nvoid X() {}\n")
        self.commit("insert a line in the middle of the block")
        code, out, _err = self.run_cli("--diff", base)
        self.assertEqual(code, 1)
        self.assertIn("Sample.cs:1: C1", out)

    def test_a_new_block_is_reported_even_when_a_larger_one_predates_it(self):
        old = "// prose one\n// prose two\n// prose three\n// prose four\npublic int X;\n"
        self.write("Sample.cs", old)
        base = self.commit("base")
        self.write("Sample.cs", old + "// fresh one\n// fresh two\n")
        self.commit("append a fresh block")
        code, out, _err = self.run_cli("--diff", base)
        self.assertEqual(code, 1)
        self.assertIn("Sample.cs:6: C1", out)
        self.assertNotIn("Sample.cs:1: C1", out)

    def test_growing_an_assertion_message_past_the_budget_is_reported(self):
        self.write("Sample.cs", 'x.Should().Be(1,\n    because: "one"\n        + " two");\n')
        base = self.commit("base")
        self.write("Sample.cs", 'x.Should().Be(1,\n    because: "one"\n        + " two"\n'
                                '        + " three"\n        + " four");\n')
        self.commit("grow the message past the budget")
        code, out, _err = self.run_cli("--diff", base)
        self.assertEqual(code, 1)
        self.assertIn("Sample.cs:2: C5", out)

    def test_a_non_ascii_path_is_reported_under_its_real_name(self):
        self.write("café.cs", "public int X;\n")
        base = self.commit("base")
        self.write("café.cs", "public int X;\n// prose one\n// prose two\n")
        self.commit("add a block")
        code, out, _err = self.run_cli("--diff", base)
        self.assertEqual(code, 1)
        self.assertIn("café.cs:2: C1", out)

    def test_an_ordinary_ref_expression_is_accepted(self):
        self.write("Sample.cs", "public int X;\n")
        self.commit("base")
        self.write("Sample.cs", "public int X;\n// prose one\n// prose two\n")
        self.commit("add a block")
        code, out, err = self.run_cli("--diff", "HEAD~1")
        self.assertEqual((code, err), (1, ""))
        self.assertIn("Sample.cs:2: C1", out)

    def test_a_base_that_does_not_resolve_exits_two_never_zero(self):
        self.write("Sample.cs", "// prose one\n// prose two\n")
        self.commit("base")
        code, out, err = self.run_cli("--diff", "origin/main")
        self.assertEqual(code, 2)
        self.assertIn("'origin/main' does not resolve to a commit (git rev-parse failed: fatal: ", err)
        self.assertNotIn("clean", out)

    def test_the_base_is_resolved_once(self):
        self.write("Sample.cs", "public int X;\n")
        self.commit("base")
        with mock.patch.object(gitio, "_git", wraps=gitio._git) as git:
            self.assertEqual(self.run_cli("--diff", "HEAD")[0], 0)
        self.assertEqual([call.args[1] for call in git.call_args_list].count("rev-parse"), 2)

    def test_a_malformed_base_exits_two(self):
        self.write("Sample.cs", "public int X;\n")
        self.commit("base")
        for base in ("--output=x", "a b", "$(id)", ""):
            code, _out, err = self.run_cli("--diff=" + base)
            self.assertEqual(code, 2, base)
            self.assertIn("is not a valid git ref", err)

    def test_outside_a_work_tree_exits_two(self):
        shutil.rmtree(os.path.join(self.tmp, ".git"))
        code, out, err = self.run_cli("--diff", "HEAD")
        self.assertEqual(code, 2)
        self.assertIn("not a git repository", err)
        self.assertNotIn("clean", out)

    def test_a_changed_file_that_cannot_be_lexed_exits_two(self):
        self.write("a.ts", "const a = 1;\n")
        base = self.commit("base")
        self.write("a.ts", "const a = `never closes\n")
        self.commit("break it")
        code, _out, err = self.run_cli("--diff", base)
        self.assertEqual(code, 2)
        self.assertIn("a.ts:1: could not scan: unterminated template literal", err)

    def test_deleted_and_excluded_files_are_not_judged(self):
        self.write("Gone.cs", "// one\n// two\n")
        self.write("public/worker.js", "const a = 1;\n")
        self.write(".agent-comment-lint.json", '{"exclude": [{"path": "public/", "reason": "generated"}]}')
        base = self.commit("base")
        os.remove(os.path.join(self.tmp, "Gone.cs"))
        self.write("public/worker.js", "// one\n// two\n")
        self.commit("delete one, dirty an excluded one")
        self.assertEqual(self.run_cli("--diff", base)[:2], (0, "agent-comment-lint: clean, 0 file(s) scanned.\n"))


class TestStagedMode(Sandbox):
    def setUp(self):
        super().setUp()
        self.init_repo()

    def test_only_staged_new_lines_are_judged(self):
        self.write("a.ts", "// one\n// two\nconst a = 1;\n")
        self.commit("old findings")
        self.write("a.ts", "// one\n// two\nconst a = 1;\n// three\n// four\n")
        self.git("add", "a.ts")
        code, out, _err = self.run_cli("--staged")
        self.assertEqual(code, 1)
        self.assertIn("a.ts:4: C1:", out)
        self.assertNotIn("a.ts:1:", out)

    def test_an_unstaged_violation_is_not_judged(self):
        self.write("a.ts", "const a = 1;\n")
        self.commit("clean")
        self.write("a.ts", "const a = 2;\n")
        self.git("add", "a.ts")
        self.write("a.ts", "// one\n// two\nconst a = 2;\n")
        self.assertEqual(self.run_cli("--staged")[0], 0)

    def test_before_the_first_commit_every_staged_line_is_judged(self):
        self.write("a.ts", "// one\n// two\n")
        self.git("add", "a.ts")
        self.assertEqual(self.run_cli("--staged")[0], 1)

    def test_a_staged_file_that_is_not_utf_8_is_judged_as_diff_judges_it(self):
        self.write_bytes("a.ts", "// caf\u00e9 one\n// two\n".encode("latin-1"))
        self.git("add", "a.ts")
        code, out, err = self.run_cli("--staged")
        self.assertEqual((code, out.splitlines()[0], err), (1, "a.ts:1: C1: 2-line prose block (limit 1)", ""))

    def test_a_staged_binary_file_that_is_not_utf_8_cannot_be_scanned(self):
        self.write_bytes("a.ts", b"// caf\xe9\x00\n")
        self.git("add", "a.ts")
        code, out, err = self.run_cli("--staged")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("a.ts: could not scan: " + cli.BINARY_NOT_TEXT, err)

    def test_nothing_staged_is_clean(self):
        self.write("a.ts", "const a = 1;\n")
        self.commit("clean")
        self.assertEqual(self.run_cli("--staged"), (0, CLEAN_NONE, ""))

    def test_a_root_below_the_top_level_reads_its_own_file_from_the_index(self):
        self.write("a.ts", "// one\n// two\n")
        self.write("sub/a.ts", "const a = 1;\n")
        self.commit("base")
        self.write("sub/a.ts", "const a = 1;\n// three\n// four\n")
        self.git("add", "sub/a.ts")
        code, out, _err = self.run_cli("--staged", "--root", "sub")
        self.assertEqual(code, 1)
        self.assertIn("a.ts:2: C1:", out)

    def test_a_blob_that_cannot_be_read_is_exit_2_and_names_the_file(self):
        self.write("a.ts", "// one\n// two\n")
        self.git("add", "a.ts")
        with mock.patch.object(cli.gitio, "read_blobs", side_effect=cli.gitio.GitError("no blob")):
            code, out, err = self.run_cli("--staged")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("a.ts: could not scan: no blob", err)

    def test_an_unmerged_path_cannot_be_scanned_and_the_other_staged_paths_are_still_judged(self):
        self.write("a.ts", "const a = 0;\n")
        self.commit("base")
        self.git("checkout", "-q", "-b", "other")
        self.write("a.ts", "const a = 1;\n")
        self.commit("other")
        self.git("checkout", "-q", "-")
        self.write("a.ts", "const a = 2;\n")
        self.commit("mine")
        subprocess.run(["git", "merge", "-q", "other"], cwd=self.tmp, capture_output=True)
        self.write("c.ts", "// one\n// two\n")
        self.git("add", "c.ts")
        code, out, err = self.run_cli("--staged")
        self.assertEqual(code, 2)
        self.assertIn("c.ts:1: C1:", out)
        self.assertIn("a.ts: could not scan: " + cli.STAGED_UNMERGED, err)
        self.assertNotIn("c.ts: could not scan", err)

    def test_the_blobs_are_read_in_a_number_of_git_calls_that_does_not_grow_with_the_files(self):
        def git_calls(count):
            for index in range(count):
                self.write("f%d.ts" % index, "// one\n// two\n")
            self.git("add", "-A")
            with mock.patch.object(gitio, "_git_bytes", wraps=gitio._git_bytes) as git:
                self.assertEqual(self.run_cli("--staged")[0], 1)
            return git.call_count

        self.assertEqual(git_calls(1), git_calls(30))


class TestStagedModeOutsideGit(Sandbox):
    def test_staged_needs_a_repository(self):
        self.assertEqual(self.run_cli("--staged")[0], 2)


class TestDiffShape(Sandbox):
    """Git settings and source lines that reshape the diff must not turn a finding into a clean run."""

    DIRTY = "public int X;\n// see PRD-1 for the rule\n// and a second line of prose\n"
    EXPECTED = ["Sample.cs:2: C1: 2-line prose block (limit 1)", "Sample.cs:2: C3: governance reference 'PRD-1'",
                "agent-comment-lint: 2 violation(s) in 1 of 1 file(s) scanned."]

    def setUp(self):
        super().setUp()
        self.init_repo()
        self.write("Sample.cs", "public int X;\n")
        self.base = self.commit("base")

    def assert_reported_with(self, *setting):
        self.write("Sample.cs", self.DIRTY)
        self.commit("add a block")
        self.git("config", *setting)
        code, out, err = self.run_cli("--diff", self.base)
        self.assertEqual((code, out.splitlines(), err), (1, self.EXPECTED, ""), setting)

    def test_colour_forced_on(self):
        self.assert_reported_with("color.ui", "always")

    def test_colour_forced_on_for_diffs(self):
        self.assert_reported_with("color.diff", "always")

    def test_a_configured_destination_prefix(self):
        self.assert_reported_with("diff.dstPrefix", "new/")

    def test_a_configured_source_prefix(self):
        self.assert_reported_with("diff.srcPrefix", "old/")

    def test_no_prefix(self):
        self.assert_reported_with("diff.noprefix", "true")

    def test_mnemonic_prefixes(self):
        self.assert_reported_with("diff.mnemonicPrefix", "true")

    def test_an_external_diff_program(self):
        self.assert_reported_with("diff.external", "true")

    def test_a_text_conversion_filter(self):
        self.write(".gitattributes", "*.cs diff=blank\n")
        self.assert_reported_with("diff.blank.textconv", "true")

    def test_a_configured_context(self):
        self.assert_reported_with("diff.context", "7")

    def test_a_context_set_through_the_environment(self):
        with mock.patch.dict(os.environ, {"GIT_DIFF_OPTS": "--unified=7"}):
            self.assert_reported_with("diff.renames", "true")

    def test_context_between_hunks(self):
        self.write("Sample.cs", "// a\nint a;\nint b;\n// b\n")
        base = self.commit("two comments apart")
        self.write("Sample.cs", "// see PRD-1\nint a;\nint b;\n// see PRD-2\n")
        self.commit("touch both")
        self.git("config", "diff.interHunkContext", "5")
        code, out, err = self.run_cli("--diff", base)
        self.assertEqual((code, err), (1, ""))
        self.assertEqual(out.splitlines()[:2], ["Sample.cs:1: C3: governance reference 'PRD-1'",
                                                "Sample.cs:4: C3: governance reference 'PRD-2'"])

    def test_a_renamed_file_is_judged_on_its_changed_lines_whatever_the_rename_setting(self):
        old = "// see ADR-0001\n" + "".join("int a%d;\n" % index for index in range(20))
        self.write("Old Name.cs", old)
        base = self.commit("a file with an old violation")
        self.git("mv", "Old Name.cs", "New Name.cs")
        self.write("New Name.cs", old + "int z;\n")
        self.commit("rename and append")
        for setting in ("true", "false"):
            self.git("config", "diff.renames", setting)
            self.assertEqual(self.run_cli("--diff", base), (0, CLEAN_ONE, ""), setting)
        self.write("New Name.cs", old + "int z;\n// see ADR-0002\n")
        self.commit("add a violation to the renamed file")
        code, out, _err = self.run_cli("--diff", base)
        self.assertEqual((code, out.splitlines()[0]), (1, "New Name.cs:23: C3: governance reference 'ADR-0002'"))

    def test_a_diff_git_did_not_shape_as_asked_is_no_verdict(self):
        self.write("Sample.cs", self.DIRTY)
        self.commit("add a block")
        shaped = gitio.changed_diff(self.tmp, (self.base + "...HEAD",))
        for unexpected in (shaped.replace("+++ b/", "+++ new/"), shaped.replace("+++ ", "\x1b[1m+++ "), ""):
            with mock.patch.object(gitio, "changed_diff", return_value=unexpected):
                code, out, err = self.run_cli("--diff", self.base)
            self.assertEqual((code, out), (2, ""), unexpected)
            self.assertIn("Sample.cs: could not scan: git counts 2 added line(s) but its diff shows 0", err)

    def test_ranges_filed_under_the_wrong_file_are_no_verdict(self):
        self.write("Sample.cs", self.DIRTY)
        self.write("Other.cs", "public int Y;\n")
        self.commit("add a block and a file")
        shaped = gitio.changed_diff(self.tmp, (self.base + "...HEAD",))
        moved = shaped.replace("+++ b/Sample.cs", "+++ b/Other.cs")
        with mock.patch.object(gitio, "changed_diff", return_value=moved):
            code, _out, err = self.run_cli("--diff", self.base)
        self.assertEqual(code, 2)
        self.assertIn("Other.cs: could not scan: git counts 1 added line(s) but its diff shows 3", err)
        self.assertIn("Sample.cs: could not scan: git counts 2 added line(s) but its diff shows 0", err)

    def test_an_added_line_shaped_like_a_file_header_keeps_its_file(self):
        self.write("a.ts", "let i = 0;\nlet j = 0;\nexport {};\n")
        base = self.commit("base")
        self.write("a.ts", "let i = 0;\n++ i;\nlet j = 0;\n// see PRD-1 for the rule\n// and more\nexport {};\n")
        self.commit("add an increment and a block")
        code, out, err = self.run_cli("--diff", base)
        self.assertEqual((code, err), (1, ""))
        self.assertEqual(out.splitlines()[:2], ["a.ts:4: C1: 2-line prose block (limit 1)",
                                                "a.ts:4: C3: governance reference 'PRD-1'"])

    def test_a_replaced_line_pair_shaped_like_file_headers_keeps_its_file(self):
        self.write("a.ts", "let i = 9;\n-- i;\nlet j = 0;\nexport {};\n")
        base = self.commit("base")
        self.write("a.ts", "let i = 9;\n++ i;\nlet j = 0;\n// see PRD-1\nexport {};\n")
        self.commit("swap the decrement and add a reference")
        code, out, err = self.run_cli("--diff", base)
        self.assertEqual((code, err, out.splitlines()[0]), (1, "", "a.ts:4: C3: governance reference 'PRD-1'"))

    def test_a_count_record_git_cut_short_is_no_verdict(self):
        self.write("Sample.cs", self.DIRTY)
        self.commit("add a block")
        real = gitio._git

        def cut_short(root, *args):
            return "2\t0" if "--numstat" in args else real(root, *args)

        with mock.patch.object(gitio, "_git", side_effect=cut_short):
            code, out, err = self.run_cli("--diff", self.base)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("git: could not scan: git diff --numstat printed a record that cannot be read", err)

    def test_files_git_shows_no_text_for_are_not_refused(self):
        self.write("Empty.cs", "")
        self.write("Moved.cs", "public int M;\n")
        self.write("Mode.sh", "echo hi\n")
        base = self.commit("three files")
        self.git("mv", "Moved.cs", "Moved2.cs")
        self.write("Fresh.cs", "")
        self.make_executable("Mode.sh")
        self.commit("a pure rename, an empty new file and a mode change")
        self.assertEqual(self.run_cli("--diff", base), (0, CLEAN_ONE, ""))

    def test_a_mode_change_or_a_pure_rename_of_a_text_file_does_not_read_it(self):
        self.write("Raw.cs", 'var s = """\n')
        self.write("Moved.cs", 'var s = """\n')
        base = self.commit("two files that do not lex")
        self.make_executable("Raw.cs")
        self.git("mv", "Moved.cs", "Moved2.cs")
        self.commit("make one executable and rename the other")
        self.assertEqual(self.run_cli("--diff", base), (0, CLEAN_NONE, ""))


class TestChangedFileGitCallsBinary(Sandbox):
    """Git prints no changed lines for a file it treats as binary, so the whole file is judged."""

    def setUp(self):
        super().setUp()
        self.init_repo()
        self.write("keep.txt", "x\n")
        self.base = self.commit("base")

    def mark_ts_binary(self):
        self.write(".gitattributes", "*.ts -diff\n")

    def test_a_text_file_an_attribute_marks_as_binary_is_judged(self):
        self.mark_ts_binary()
        self.write("t.ts", "// one\n// two\n")
        self.commit("add a block")
        code, out, err = self.run_cli("--diff", self.base)
        self.assertEqual((code, out.splitlines()[0], err), (1, "t.ts:1: C1: 2-line prose block (limit 1)", ""))

    def test_every_line_of_it_counts_as_changed(self):
        self.mark_ts_binary()
        self.write("t.ts", "// see ADR-0001\nlet a = 1;\n")
        base = self.commit("a file with an old violation")
        self.write("t.ts", "// see ADR-0001\nlet a = 2;\n")
        self.commit("touch another line")
        code, out, _err = self.run_cli("--diff", base)
        self.assertEqual((code, out.splitlines()[0]), (1, "t.ts:1: C3: governance reference 'ADR-0001'"))

    def test_a_mode_change_alone_judges_no_line(self):
        self.mark_ts_binary()
        self.write("t.ts", "// one\n// two\n")
        base = self.commit("a file with an old block")
        self.make_executable("t.ts")
        self.commit("make it executable")
        self.assertEqual(self.run_cli("--diff", base), (0, CLEAN_NONE, ""))

    def test_a_pure_rename_judges_no_line(self):
        self.mark_ts_binary()
        self.write("t.ts", "// one\n// two\n")
        base = self.commit("a file with an old block")
        self.git("mv", "t.ts", "u.ts")
        self.commit("rename it")
        self.assertEqual(self.run_cli("--diff", base), (0, CLEAN_NONE, ""))

    def test_a_rename_that_also_changes_it_still_judges_every_line(self):
        self.mark_ts_binary()
        self.write("t.ts", "// one\n// two\n" + "let a = 1;\n" * 20)
        base = self.commit("a file with an old block")
        self.git("mv", "t.ts", "u.ts")
        self.write("u.ts", "// one\n// two\n" + "let a = 1;\n" * 19 + "let a = 2;\n")
        self.commit("rename it and change a line")
        code, out, _err = self.run_cli("--diff", base)
        self.assertEqual((code, out.splitlines()[0]), (1, "u.ts:1: C1: 2-line prose block (limit 1)"))

    def test_a_mode_change_alone_of_a_file_that_is_not_utf_8_is_not_refused(self):
        self.write_bytes("Wide.cs", "// one\n// two\n".encode("utf-16"))
        base = self.commit("a UTF-16 file")
        self.make_executable("Wide.cs")
        self.commit("make it executable")
        self.assertEqual(self.run_cli("--diff", base), (0, CLEAN_NONE, ""))

    def test_a_mode_change_alone_does_not_read_the_file(self):
        self.write(".gitattributes", "*.cs -diff\n")
        self.write("Raw.cs", 'var s = """\n')
        base = self.commit("a file that does not lex")
        self.make_executable("Raw.cs")
        self.commit("make it executable")
        self.assertEqual(self.run_cli("--diff", base), (0, CLEAN_NONE, ""))

    def test_a_file_that_holds_a_nul_byte_is_judged(self):
        self.write_bytes("Blob.cs", b"int x;\x00\n")
        base = self.commit("a file with a NUL byte")
        self.write_bytes("Blob.cs", b"int y;\x00\n")
        self.commit("change it")
        self.assertEqual(self.run_cli("--diff", base), (0, CLEAN_ONE, ""))
        self.write_bytes("Blob.cs", b"int y;\x00\n// one\n// two\n")
        self.commit("add a block")
        code, out, _err = self.run_cli("--diff", base)
        self.assertEqual((code, out.splitlines()[0]), (1, "Blob.cs:2: C1: 2-line prose block (limit 1)"))

    def test_one_that_is_not_utf_8_is_no_verdict_and_the_rest_is_still_judged(self):
        self.write_bytes("Wide.cs", "// one\n// two\n".encode("utf-16"))
        self.write("Dirty.cs", "// see ADR-0001\n")
        self.commit("add a UTF-16 file and a UTF-8 one")
        code, out, err = self.run_cli("--diff", self.base)
        self.assertEqual((code, out), (2, "Dirty.cs:1: C3: governance reference 'ADR-0001'\n"))
        self.assertIn("Wide.cs: could not scan: git shows no changed lines for it (a binary file) and it is not "
                      "UTF-8 text", err)

    def test_an_excluded_one_is_not_judged(self):
        self.write_bytes("public/Wide.cs", "// one\n// two\n".encode("utf-16"))
        self.write(".agent-comment-lint.json", '{"exclude": [{"path": "public/", "reason": "generated"}]}')
        self.commit("add an excluded UTF-16 file")
        self.assertEqual(self.run_cli("--diff", self.base), (0, "agent-comment-lint: clean, 0 file(s) scanned.\n", ""))


@unittest.skipIf(os.name == "nt", "these characters cannot be in a file name there")
class TestChangedFileNamesGitQuotes(Sandbox):
    """Git quotes a name that holds a quote, a backslash or a control character, whatever its settings say."""

    def assert_block_is_reported_in(self, name):
        self.init_repo()
        self.write(name, "int a;\n")
        base = self.commit("base")
        self.write(name, "int a;\n// one\n// two\n")
        self.commit("add a block")
        code, out, err = self.run_cli("--diff", base)
        self.assertEqual((code, out.splitlines()[0], err), (1, name + ":2: C1: 2-line prose block (limit 1)", ""))

    def test_a_double_quote(self):
        self.assert_block_is_reported_in('we"ird.cs')

    def test_a_backslash(self):
        self.assert_block_is_reported_in("back\\slash.cs")

    def test_a_tab(self):
        self.assert_block_is_reported_in("tab\there.cs")

    def test_a_quote_beside_a_letter_outside_ascii(self):
        self.assert_block_is_reported_in('caf\u00e9 "x".cs')

    def test_a_new_file_with_a_quoted_name(self):
        self.init_repo()
        self.write("keep.txt", "x\n")
        base = self.commit("base")
        self.write('dir/we"ird.cs', "int a;\nint b;\nint c;\n")
        self.commit("add a file")
        self.assertEqual(self.run_cli("--diff", base), (0, CLEAN_ONE, ""))


class TestStdinMode(Sandbox):
    def test_the_text_on_standard_input_is_judged_as_the_named_path(self):
        code, out, _err = self.run_cli("--stdin-path", "src/new.py", stdin='def f():\n    """One.\n    Two."""\n')
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[0], "src/new.py:2: C1: 2-line prose block (limit 1)")

    def test_the_file_on_disk_is_not_read(self):
        self.write("a.ts", "// one\n// two\n")
        self.assertEqual(self.run_cli("--stdin-path", "a.ts", stdin="const a = 1;\n")[0], 0)

    def test_a_byte_order_mark_on_a_text_stream_does_not_hide_the_first_line(self):
        code, out, _err = self.run_cli("--stdin-path", "a.cs", stdin="\ufeff// one\n// two\n")
        self.assertEqual((code, out.splitlines()[0]), (1, "a.cs:1: C1: 2-line prose block (limit 1)"))

    def test_standard_input_is_read_as_utf_8_whatever_encoding_the_stream_was_given(self):
        body = "\ufeff// café one\n// two\n".encode("utf-8")
        done = subprocess.run([sys.executable, os.path.join(REPO, "check-agent-comment-lint.py"),
                               "--stdin-path", "a.cs"],
                              cwd=self.tmp, input=body, capture_output=True,
                              env=dict(os.environ, PYTHONIOENCODING="latin-1"))
        self.assertEqual((done.returncode, done.stdout.decode("latin-1").splitlines()[0]),
                         (1, "a.cs:1: C1: 2-line prose block (limit 1)"))

    def test_text_that_cannot_be_lexed_exits_two(self):
        self.assertEqual(self.run_cli("--stdin-path", "a.ts", stdin="const a = `x\n")[0], 2)

    def test_the_json_document_names_the_mode(self):
        self.write("a.ts", "const a = 1;\n")
        self.assertEqual(json.loads(self.run_cli("--stdin-path", "a.ts", "--json", stdin="")[1])["mode"], "stdin")
        self.assertEqual(json.loads(self.run_cli("--files", "a.ts", "--json")[1])["mode"], "files")


class TestHookMode(Sandbox):
    """A proposed write: the whole file it would leave is judged, and only findings on the lines it touched block."""

    def hook(self, stdin, cwd=None):
        return self.run_cli("--hook", stdin=stdin, cwd=cwd)

    def assert_blocked(self, result, *expected):
        code, out, err = result
        self.assertEqual((code, out), (2, ""), err)
        self.assertTrue(err.startswith("Blocked: agent-comment-lint rejects this write.\n"), err)
        for text in expected:
            self.assertIn(text, err)

    @unittest.skipUnless(os.name == "nt", "drive letters and case-insensitive paths are Windows behaviour")
    def test_a_windows_path_in_another_case_and_separator_is_judged(self):
        path = (self.tmp.upper() + "/a.ts").replace("\\", "/")
        self.assert_blocked(self.hook(event("Write", path, content="// one\n// two\n")), ":1: C1:")

    def test_a_new_finding_in_the_edit_blocks_it(self):
        self.write("a.ts", "const a = 1;\n")
        result = self.hook(event("Edit", "a.ts", old_string="const a = 1;\n",
                                 new_string="// one\n// two\nconst a = 1;\n"))
        self.assert_blocked(result, "a.ts:1: C1: 2-line prose block (limit 1)")

    def test_a_blocked_edit_shows_the_comment_and_the_fix(self):
        self.write("a.ts", "const a = 1;\n")
        result = self.hook(event("Edit", "a.ts", old_string="const a = 1;\n",
                                 new_string="// one\n// two\nconst a = 1;\n"))
        self.assert_blocked(result, "a.ts:1: C1: 2-line prose block (limit 1)\n    // one\n    // two\n  Fix: ",
                            "Only the lines this write adds or changes are judged", report.HOOK_CLOSING[0])
        self.assertNotIn(report.WRITE_RETRY, result[2])

    def test_a_blocked_write_is_told_to_resend_only_the_comment_lines(self):
        self.assert_blocked(self.hook(event("Write", "new.ts", content="// see ADR-9\n")), report.WRITE_RETRY)

    def test_an_old_finding_elsewhere_does_not_block(self):
        self.write("a.ts", "// one\n// two\nconst a = 1;\n")
        result = self.hook(event("Edit", "a.ts", old_string="const a = 1;\n",
                                 new_string="const a = 1;\nconst b = 2;\n"))
        self.assertEqual(result, (0, "", ""))

    def test_growing_an_old_block_blocks(self):
        self.write("a.ts", "// one\nconst a = 1;\n")
        result = self.hook(event("Edit", "a.ts", old_string="// one\n", new_string="// one\n// two\n"))
        self.assert_blocked(result, "a.ts:1: C1: 2-line prose block (limit 1)")

    def test_a_new_file_is_judged_on_every_line(self):
        self.assert_blocked(self.hook(event("Write", "new.ts", content="// one\n// two\n")), "new.ts:1: C1:")

    def test_a_banner_write_goes_through(self):
        content = "// ---\n// Title\n// ---\nconst a = 1;\n"
        self.assertEqual(self.hook(event("Write", "new.ts", content=content)), (0, "", ""))

    def test_prose_under_a_banner_blocks(self):
        content = "// ---\n// Title\n// ---\n// extra\nconst a = 1;\n"
        self.assert_blocked(self.hook(event("Write", "new.ts", content=content)),
                            "new.ts:2: C1: 2-line prose block (limit 1)")

    def test_a_file_left_unscannable_blocks(self):
        self.write("a.ts", "const a = 1;\n")
        result = self.hook(event("Edit", "a.ts", old_string="const a = 1;", new_string="const a = `x"))
        self.assert_blocked(result, "a.ts:1: could not scan:")

    def test_an_edit_the_tool_would_refuse_is_let_through(self):
        self.write("a.ts", "const a = 1;\n")
        refused = event("Edit", "a.ts", old_string="nope", new_string="// one\n// two\n")
        self.assertEqual(self.hook(refused), (0, "", ""))

    def test_a_tool_that_writes_no_file_is_let_through(self):
        self.assertEqual(self.hook(json.dumps({"tool_name": "Read", "tool_input": {"file_path": "a.ts"}})), (0, "", ""))

    def test_paths_the_policy_does_not_judge_are_let_through(self):
        self.write(".agent-comment-lint.json", '{"exclude": [{"path": "gen/", "reason": "generated"}]}')
        for path in ("notes.md", "gen/a.ts", os.path.join(os.path.dirname(self.tmp), "elsewhere.ts")):
            with self.subTest(path=path):
                self.assertEqual(self.hook(event("Write", path, content="// one\n// two\n")), (0, "", ""))

    def test_input_that_is_not_an_event_blocks(self):
        for stdin in ("not json", json.dumps({"tool_name": "Write", "tool_input": {}}),
                      event("Edit", "a.ts", old_string=1, new_string="b")):
            with self.subTest(stdin=stdin):
                self.assert_blocked(self.hook(stdin), "--hook: could not scan: standard input is not a Claude Code "
                                                      "hook event: ")

    def test_a_file_that_is_not_utf_8_blocks(self):
        self.write_bytes("a.ts", b"// caf\xe9\nconst a = 1;\n")
        result = self.hook(event("Edit", "a.ts", old_string="const a = 1;", new_string="const a = 2;"))
        self.assert_blocked(result, "a.ts: could not scan: is not UTF-8 text")

    def test_windows_line_endings_are_kept(self):
        self.write_bytes("a.ts", b"const a = 1;\r\n")
        result = self.hook(event("Edit", "a.ts", old_string="const a = 1;\r\n",
                                 new_string="// one\r\n// two\r\nconst a = 1;\r\n"))
        self.assert_blocked(result, "a.ts:1: C1: 2-line prose block (limit 1)")

    def test_a_newline_only_edit_of_a_windows_file_is_judged(self):
        self.write_bytes("a.ts", b"const a = 1;\r\n")
        result = self.hook(event("Edit", "a.ts", old_string="const a = 1;\n",
                                 new_string="// one\n// two\nconst a = 1;\n"))
        self.assert_blocked(result, "a.ts:1: C1: 2-line prose block (limit 1)")

    def test_overwriting_a_file_judges_only_the_lines_it_changes(self):
        self.write("a.ts", "// one\n// two\nconst a = 1;\n")
        kept = event("Write", "a.ts", content="// one\n// two\nconst a = 1;\nconst b = 2;\n")
        self.assertEqual(self.hook(kept), (0, "", ""))
        added = event("Write", "a.ts", content="// one\n// two\nconst a = 1;\n// three\n// four\nconst b = 2;\n")
        self.assert_blocked(self.hook(added), "a.ts:4: C1: 2-line prose block (limit 1)")

    def test_a_write_over_a_file_that_is_not_utf_8_judges_every_line(self):
        self.write_bytes("a.ts", b"// caf\xe9\n")
        self.assert_blocked(self.hook(event("Write", "a.ts", content="// one\n// two\n")), "a.ts:1: C1:")
        self.assertEqual(self.hook(event("Write", "a.ts", content="const a = 1;\n")), (0, "", ""))

    def test_a_crash_in_the_hook_blocks(self):
        self.write("a.ts", "const a = 1;\n")
        with mock.patch.object(cli, "_run_hook", side_effect=RuntimeError("boom")):
            result = self.hook(event("Write", "a.ts", content="x\n"))
        self.assert_blocked(result, "boom")

    def test_a_path_with_a_nul_byte_blocks(self):
        self.assert_blocked(self.hook(event("Write", "a\x00.ts", content="x\n")))

    @unittest.skipIf(os.name == "nt", "a Windows file name may hold a lone surrogate")
    def test_a_path_with_a_lone_surrogate_blocks(self):
        self.assert_blocked(self.hook(event("Write", "a\ud800.ts", content="x\n")))

    @unittest.skipUnless(os.name == "nt", "a Windows file name may hold a lone surrogate")
    def test_a_path_with_a_lone_surrogate_is_judged_like_any_other(self):
        self.assert_blocked(self.hook(event("Write", "a\ud800.ts", content="// one\n// two\n")), ":1: C1:")

    def test_deeply_nested_input_blocks(self):
        self.assert_blocked(self.hook("[" * 200000))

    def test_a_settings_file_that_is_not_utf_8_blocks(self):
        self.write_bytes(".agent-comment-lint.json", b"\xff\xfe{")
        self.assert_blocked(self.hook(event("Write", "a.ts", content="x\n")), "could not scan")

    def test_input_that_is_not_utf_8_blocks(self):
        stdin = io.TextIOWrapper(io.BytesIO(event("Write", "a.ts", content="x\n").encode()[:-2] + b'\xff"}}'))
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(["--hook"], stdin=stdin, stdout=out, stderr=err, cwd=self.tmp)
        self.assert_blocked((code, out.getvalue(), err.getvalue()), "standard input is not a Claude Code")

    def test_a_bad_settings_file_does_not_block_a_write_it_never_judges(self):
        self.write(".agent-comment-lint.json", "{")
        outside = os.path.join(os.path.dirname(self.tmp), "elsewhere.ts")
        for stdin in (json.dumps({"tool_name": "Read", "tool_input": {"file_path": "a.ts"}}),
                      event("Write", "notes.md", content="x\n"), event("Write", outside, content="x\n")):
            with self.subTest(stdin=stdin):
                self.assertEqual(self.hook(stdin), (0, "", ""))
        self.assert_blocked(self.hook(event("Write", "a.ts", content="x\n")), "could not scan")

    def test_an_absolute_path_from_a_subdirectory(self):
        self.init_repo()
        self.write("src/a.ts", "const a = 1;\n")
        absolute = os.path.join(self.tmp, "src", "a.ts")
        edit = event("Edit", absolute, old_string="const a = 1;\n", new_string="// one\n// two\nconst a = 1;\n")
        result = self.hook(edit, cwd=os.path.join(self.tmp, "src"))
        self.assert_blocked(result, "src/a.ts:1: C1:")

    def other_tree(self):
        """A fresh directory outside the sandbox, removed after the test."""
        path = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        os.rmdir(path)
        return path

    def test_a_write_into_another_worktree_of_the_repository_is_judged_there(self):
        self.init_repo()
        self.write("a.ts", "const a = 1;\n")
        self.commit("start")
        worktree = self.other_tree()
        self.git("worktree", "add", "-q", worktree, "-b", "task")
        with open(os.path.join(worktree, ".agent-comment-lint.json"), "w", encoding="utf-8") as handle:
            handle.write('{"exclude": [{"path": "gen/", "reason": "generated"}]}')
        subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "exclude gen"], cwd=worktree, check=True)
        prose = "// one\n// two\nconst a = 1;\n"
        self.assert_blocked(self.hook(event("Write", os.path.join(worktree, "src", "new", "b.ts"), content=prose)),
                            "src/new/b.ts:1: C1:")
        self.assertEqual(self.hook(event("Write", os.path.join(worktree, "gen", "b.ts"), content=prose)), (0, "", ""))
        self.assertEqual(self.hook(event("Write", os.path.join(self.tmp, "gen", "b.ts"), content=prose))[0], 2)

    def test_a_write_into_another_repository_is_let_through(self):
        self.init_repo()
        other = self.other_tree()
        os.makedirs(other)
        subprocess.run(("git", "init", "-q"), cwd=other, capture_output=True, check=True)
        self.assertEqual(self.hook(event("Write", os.path.join(other, "a.ts"), content="// one\n// two\n")),
                         (0, "", ""))


class TestHookAgents(Sandbox):
    """The per-target loop, through a test-only agent whose event lists targets as [tool, path, input, must_apply]."""

    PROSE = "// one\n// two\nconst a = 1;\n"

    def run_fake(self, *targets, cwd=None):
        stdin = json.dumps({"targets": [list(target) for target in targets]})
        adapters = {"fake": lambda found: [hook.Target(*target) for target in found["targets"]]}
        with mock.patch.dict(hook.ADAPTERS, adapters), mock.patch.dict(hook.TITLES, {"fake": "Fake"}):
            return self.run_cli("--hook", "--agent", "fake", stdin=stdin, cwd=cwd)

    def write_target(self, path, content=None):
        return ("Write", path, {"file_path": path, "content": content or self.PROSE}, False)

    def edit_target(self, path, must_apply):
        return ("Edit", path, {"file_path": path, "old_string": "absent", "new_string": "x"}, must_apply)

    def test_every_target_is_judged_and_reported(self):
        code, out, err = self.run_fake(self.write_target("a.ts"), self.write_target("b.ts"))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("a.ts:1: C1:", err)
        self.assertIn("b.ts:1: C1:", err)

    def test_a_target_out_of_scope_is_not_judged(self):
        code, _out, err = self.run_fake(self.write_target("a.ts"), self.write_target("notes.txt"))
        self.assertEqual(code, 2)
        self.assertIn("a.ts:1: C1:", err)
        self.assertNotIn("notes.txt", err)

    def test_an_edit_that_must_apply_and_does_not_is_an_error(self):
        self.write("a.ts", "const a = 1;\n")
        code, _out, err = self.run_fake(self.edit_target("a.ts", True))
        self.assertEqual(code, 2)
        self.assertIn(cli.PATCH_NOT_APPLIED, err)

    def test_an_edit_that_need_not_apply_is_let_through(self):
        self.write("a.ts", "const a = 1;\n")
        self.assertEqual(self.run_fake(self.edit_target("a.ts", False)), (0, "", ""))

    def test_a_sibling_worktree_does_not_leak_into_the_next_target(self):
        self.init_repo()
        self.write("a.ts", "const a = 1;\n")
        self.commit("start")
        worktree = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, worktree, ignore_errors=True)
        os.rmdir(worktree)
        self.git("worktree", "add", "-q", worktree, "-b", "task")
        with open(os.path.join(worktree, ".agent-comment-lint.json"), "w", encoding="utf-8") as handle:
            handle.write('{"exclude": [{"path": "gen/", "reason": "generated"}]}')
        subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "exclude gen"], cwd=worktree, check=True)
        code, _out, err = self.run_fake(self.write_target(os.path.join(worktree, "gen", "b.ts")),
                                        self.write_target(os.path.join(self.tmp, "gen", "b.ts")))
        self.assertEqual(code, 2)
        self.assertIn("gen/b.ts:1: C1:", err)

    def test_the_write_retry_line_is_for_claude_only(self):
        _code, _out, err = self.run_fake(self.write_target("a.ts"))
        self.assertNotIn(report.WRITE_RETRY, err)
        _code, _out, err = self.run_cli("--hook", stdin=event("Write", "a.ts", content=self.PROSE))
        self.assertIn(report.WRITE_RETRY, err)

    def test_claude_by_name_is_the_default(self):
        for content in (self.PROSE, "const a = 1;\n"):
            stdin = event("Write", "a.ts", content=content)
            self.assertEqual(self.run_cli("--hook", "--agent", "claude", stdin=stdin),
                             self.run_cli("--hook", stdin=stdin))


class TestHookCodex(Sandbox):
    """`--hook --agent codex` on the documented apply_patch event, its patch paths relative to the event's cwd."""

    def run_codex(self, *lines, cwd=None):
        patch = "\n".join(("*** Begin Patch",) + lines + ("*** End Patch",))
        stdin = json.dumps(dict(fixture("codex-write"), cwd=cwd or self.tmp, tool_input={"command": patch}))
        return self.run_cli("--hook", "--agent", "codex", stdin=stdin)

    def test_an_added_file_with_a_two_line_comment_is_blocked(self):
        code, out, err = self.run_codex("*** Add File: a.ts", "+// one", "+// two")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("a.ts:1: C1: 2-line prose block (limit 1)", err)

    def test_a_clean_added_file_passes_silently(self):
        self.assertEqual(self.run_codex("*** Add File: a.ts", "+const a = 1;"), (0, "", ""))

    def test_the_second_file_of_a_patch_is_judged_and_named(self):
        self.write("a.ts", "const a = 1;\n")
        code, _out, err = self.run_codex("*** Update File: a.ts", "@@", "-const a = 1;", "+const a = 2;",
                                         "*** Add File: b.ts", "+// one", "+// two", "+const b = 1;")
        self.assertEqual(code, 2)
        self.assertIn("b.ts:1: C1:", err)
        self.assertNotIn("a.ts", err)

    def test_a_patch_that_only_deletes_is_not_judged(self):
        self.write("a.ts", "// one\n// two\nconst a = 1;\n")
        self.assertEqual(self.run_codex("*** Delete File: a.ts"), (0, "", ""))

    def test_a_patch_whose_context_matches_nothing_is_blocked(self):
        self.write("a.ts", "const a = 1;\n")
        code, _out, err = self.run_codex("*** Update File: a.ts", "@@", " const z = 9;", "+// one")
        self.assertEqual(code, 2)
        self.assertIn("a.ts: could not scan: " + cli.PATCH_NOT_APPLIED, err)

    def test_an_update_is_judged_on_the_lines_it_changes(self):
        self.write("a.ts", "// old\n// comment\nfunction f() {\n  return 1;\n}\n")
        self.assertEqual(self.run_codex("*** Update File: a.ts", "@@ function f() {", "-  return 1;", "+  return 2;"),
                         (0, "", ""))
        code, _out, err = self.run_codex("*** Update File: a.ts", "@@ function f() {", "+  // one", "+  // two",
                                         "   return 1;")
        self.assertEqual(code, 2)
        self.assertIn("a.ts:4: C1:", err)

    def test_a_move_is_judged_at_its_destination_against_its_source(self):
        self.write("a.ts", "// old\n// comment\nconst a = 1;\n")
        moved = ("*** Update File: a.ts", "*** Move to: src/b.ts", "@@", " const a = 1;")
        self.assertEqual(self.run_codex(*moved + ("+const b = 2;",)), (0, "", ""))
        code, _out, err = self.run_codex(*moved + ("+// one", "+// two"))
        self.assertEqual(code, 2)
        self.assertIn("src/b.ts:4: C1:", err)
        self.assertNotIn("a.ts:", err)

    def test_a_move_whose_destination_is_out_of_scope_is_not_judged(self):
        self.write("a.ts", "const a = 1;\n")
        outside = os.path.join(os.path.dirname(self.tmp), "elsewhere.ts")
        for destination in ("notes.txt", outside):
            with self.subTest(destination=destination):
                self.assertEqual(self.run_codex("*** Update File: a.ts", "*** Move to: " + destination, "@@",
                                                " const a = 1;", "+// one", "+// two"), (0, "", ""))

    def test_a_move_from_outside_the_root_is_blocked(self):
        source = os.path.join(os.path.dirname(self.tmp), "outside.ts")
        code, _out, err = self.run_codex("*** Update File: " + source, "*** Move to: a.ts", "@@", "+const a = 1;")
        self.assertEqual(code, 2)
        self.assertIn("a.ts: could not scan: " + cli.MOVED_FROM_OUTSIDE, err)

    def test_patch_paths_are_relative_to_the_event_cwd(self):
        os.mkdir(os.path.join(self.tmp, "sub"))
        code, _out, err = self.run_codex("*** Add File: a.ts", "+// one", "+// two", cwd=os.path.join(self.tmp, "sub"))
        self.assertEqual(code, 2)
        self.assertIn("sub/a.ts:1: C1:", err)

    def test_a_patch_codex_would_refuse_is_blocked_as_not_the_event(self):
        code, _out, err = self.run_codex("*** Update File: a.ts")
        self.assertEqual(code, 2)
        self.assertIn("standard input is not a Codex hook event: ", err)


class TestRunTexts(unittest.TestCase):
    def test_only_a_text_with_findings_is_kept_for_the_hook_excerpt(self):
        run = cli._Run("all")
        run.judge("clean.ts", "const a = 1;\n")
        run.judge("dirty.ts", "// one\n// two\nconst a = 1;\n")
        self.assertEqual(sorted(run.texts), ["dirty.ts"])


class TestSettingsEncoding(Sandbox):
    def test_a_settings_file_that_is_not_utf_8_is_a_could_not_scan(self):
        self.write("a.ts", "const a = 1;\n")
        self.write_bytes(".agent-comment-lint.json", b"\xff\xfe{")
        code, out, err = self.run_cli("--all")
        self.assertEqual((code, out), (2, ""), err)
        self.assertIn(".agent-comment-lint.json: could not scan:", err)


class TestJsonOutput(Sandbox):
    def test_the_findings_are_one_json_document(self):
        self.write("Two.cs", TWO_BLOCKS)
        code, out, _err = self.run_cli("--all", "--json")
        document = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual((document["exit_code"], document["mode"], document["counts"]), (1, "all", {"C1": 2}))
        self.assertEqual([(item["path"], item["line"], item["end_line"]) for item in document["findings"]],
                         [("Two.cs", 1, 2), ("Two.cs", 4, 5)])

    def test_a_scan_problem_is_in_the_document_and_on_standard_error(self):
        code, out, err = self.run_cli("--files", "missing.cs", "--json")
        self.assertEqual((code, json.loads(out)["exit_code"]), (2, 2))
        self.assertEqual(json.loads(out)["errors"][0]["path"], "missing.cs")
        self.assertIn("missing.cs: could not scan:", err)


class TestEntryPoints(Sandbox):
    def test_version_prints_the_package_version(self):
        done = subprocess.run([sys.executable, os.path.join(REPO, "check-agent-comment-lint.py"), "--version"],
                              cwd=self.tmp, capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout), (0, "check-agent-comment-lint.py %s\n" % __version__))

    def test_the_script_runs_from_another_directory(self):
        self.write("Dirty.cs", "// one\n// two\n")
        done = subprocess.run([sys.executable, os.path.join(REPO, "check-agent-comment-lint.py"), "--all"],
                              cwd=self.tmp, capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn("Dirty.cs:1: C1: 2-line prose block (limit 1)", done.stdout)

    def test_the_module_runs_with_dash_m(self):
        self.write("Clean.cs", "public int X => 1;\n")
        done = subprocess.run([sys.executable, "-m", "agent_comment_lint", "--all"], cwd=self.tmp,
                              capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=REPO))
        self.assertEqual((done.returncode, done.stdout), (0, "agent-comment-lint: clean, 1 file(s) scanned.\n"))

    def test_this_repository_passes_its_own_policy(self):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(["--all"], stdout=out, stderr=err, cwd=REPO)
        self.assertEqual((code, err.getvalue()), (0, ""), out.getvalue())

    def test_the_hook_blocks_through_the_script(self):
        done = subprocess.run([sys.executable, os.path.join(REPO, "check-agent-comment-lint.py"), "--hook"],
                              cwd=self.tmp,
                              input=event("Write", "a.ts", content="// one\n// two\n").encode("utf-8"),
                              capture_output=True)
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertIn(b"a.ts:1: C1: 2-line prose block (limit 1)", done.stderr)


def session_event(name, session_id="s1", **extra):
    return json.dumps(dict({"hook_event_name": name, "session_id": session_id}, **extra))


class TestHookCommittedSettings(Sandbox):
    EXCLUDE_A = '{"exclude": [{"path": "a.ts", "reason": "generated"}]}'

    def setUp(self):
        super().setUp()
        self.init_repo()
        self.write("a.ts", "const a = 1;\n")
        self.commit("clean")

    def dirty_write(self):
        return self.run_cli("--hook", stdin=event("Write", "a.ts", content="// one\n// two\n"))

    def test_an_uncommitted_exclusion_does_not_let_a_violation_through(self):
        self.write(".agent-comment-lint.json", self.EXCLUDE_A)
        self.assertEqual(self.dirty_write()[0], 2)

    def test_a_committed_exclusion_does(self):
        self.write(".agent-comment-lint.json", self.EXCLUDE_A)
        self.commit("exclude a.ts")
        self.assertEqual(self.dirty_write(), (0, "", ""))

    def test_a_committed_settings_file_that_is_malformed_blocks_whatever_is_on_disk(self):
        self.write(".agent-comment-lint.json", '{"limits": {}}')
        self.commit("bad settings")
        self.write(".agent-comment-lint.json", "{}")
        self.assertEqual(self.dirty_write()[0], 2)

    def test_before_the_first_commit_the_file_on_disk_is_read(self):
        self.git("update-ref", "-d", "HEAD")
        self.write(".agent-comment-lint.json", self.EXCLUDE_A)
        self.assertEqual(self.dirty_write(), (0, "", ""))

    def test_a_committed_settings_file_that_is_not_utf_8_blocks(self):
        self.write_bytes(".agent-comment-lint.json", b"\xff\xfe{")
        self.commit("settings that are not UTF-8")
        code, _out, err = self.dirty_write()
        self.assertEqual(code, 2)
        self.assertIn(".agent-comment-lint.json: could not scan: is not UTF-8 text", err)

    def test_a_subdirectory_root_reads_its_own_settings_as_committed(self):
        self.write("sub/a.ts", "const a = 1;\n")
        self.write("sub/.agent-comment-lint.json", self.EXCLUDE_A)
        write = event("Write", "sub/a.ts", content="// one\n// two\n")
        self.assertEqual(self.run_cli("--hook", "--root", "sub", stdin=write)[0], 2)
        self.commit("exclude sub/a.ts")
        self.assertEqual(self.run_cli("--hook", "--root", "sub", stdin=write), (0, "", ""))

    def test_git_failing_while_the_committed_settings_are_read_blocks(self):
        for name in ("has_head", "committed_blob"):
            with self.subTest(name=name), mock.patch.object(gitio, name, side_effect=gitio.GitError("boom")):
                code, _out, err = self.dirty_write()
                self.assertEqual(code, 2)
                self.assertIn("git: could not scan: boom", err)

    def test_an_explicit_config_is_read_from_disk(self):
        self.write("cfg.json", self.EXCLUDE_A)
        result = self.run_cli("--hook", "--config", "cfg.json",
                              stdin=event("Write", "a.ts", content="// one\n// two\n"))
        self.assertEqual(result, (0, "", ""))


class TestSessionHooks(Sandbox):
    def setUp(self):
        super().setUp()
        self.init_repo()
        self.write("a.ts", "const a = 1;\n")
        self.commit("clean")

    def hook(self, stdin):
        return self.run_cli("--hook", stdin=stdin)

    def start(self):
        self.assertEqual(self.hook(session_event("SessionStart", source="startup")), (0, "", ""))

    def stop(self):
        return self.hook(session_event("Stop", stop_hook_active=False))

    def test_a_violation_written_outside_the_write_tools_blocks_the_stop(self):
        self.start()
        self.write("b.ts", "// one\n// two\n")
        code, out, err = self.stop()
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("Before you finish:"), err)
        self.assertIn("b.ts:1: C1: 2-line prose block (limit 1)", err)

    def test_an_uncommitted_exclusion_does_not_stop_the_stop_check_from_blocking(self):
        self.start()
        self.write("b.ts", "// one\n// two\n")
        self.write(".agent-comment-lint.json", '{"exclude": [{"path": "b.ts", "reason": "generated"}]}')
        self.assertEqual(self.stop()[0], 2)

    def test_a_violation_that_predates_the_session_does_not_block(self):
        self.write("old.ts", "// one\n// two\n")
        self.start()
        self.assertEqual(self.stop(), (0, "", ""))

    def test_an_unscannable_file_the_session_never_touched_does_not_block(self):
        self.write("broken.ts", "const a = `never closed\n")
        self.start()
        self.assertEqual(self.stop(), (0, "", ""))

    def test_a_file_the_session_breaks_blocks(self):
        self.start()
        self.write("a.ts", "const a = `never closed\n")
        self.assertEqual(self.stop()[0], 2)

    def test_a_text_file_the_session_leaves_not_utf_8_blocks_with_its_own_message(self):
        self.start()
        self.write_bytes("b.ts", "// caf\u00e9\nconst b = 1;\n".encode("latin-1"))
        code, out, err = self.stop()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("b.ts: could not scan: is not UTF-8 text", err)
        self.assertNotIn("binary", err)

    def test_a_stop_with_findings_says_it_found_them_in_what_changed(self):
        self.start()
        self.write("b.ts", "// one\n// two\n")
        _code, _out, err = self.stop()
        self.assertTrue(err.startswith(
            "Before you finish: agent-comment-lint found comments that break the policy in what changed during this "
            "session.\nOnly lines changed since this session started and not yet committed are judged.\nb.ts:1: C1:"),
            err)

    def test_a_stop_with_only_scan_errors_says_it_could_not_check(self):
        self.start()
        self.write("a.ts", "const a = `never closed\n")
        code, _out, err = self.stop()
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith(
            "Before you finish: agent-comment-lint could not check what changed during this session.\n"
            "Only lines changed since this session started and not yet committed are judged.\n"), err)
        self.assertNotIn("found comments", err)

    def test_a_fixed_violation_passes_the_next_stop(self):
        self.start()
        self.write("b.ts", "// one\n// two\n")
        self.assertEqual(self.stop()[0], 2)
        self.write("b.ts", "// one\n")
        self.assertEqual(self.stop(), (0, "", ""))

    def test_a_deleted_or_renamed_file_is_not_judged(self):
        self.write("c.ts", "// one\n// two\n")
        self.commit("old finding")
        self.start()
        os.rename(os.path.join(self.tmp, "c.ts"), os.path.join(self.tmp, "d.ts"))
        os.remove(os.path.join(self.tmp, "a.ts"))
        self.assertEqual(self.stop(), (0, "", ""))

    def test_an_ignored_file_is_not_judged(self):
        self.write(".gitignore", "scratch/\n")
        self.commit("ignore scratch")
        self.start()
        self.write("scratch/x.ts", "// one\n// two\n")
        self.assertEqual(self.stop(), (0, "", ""))

    def test_no_snapshot_lets_the_session_end(self):
        self.write("b.ts", "// one\n// two\n")
        self.assertEqual(self.stop(), (0, "", ""))

    def test_a_second_session_start_keeps_the_first_snapshot(self):
        self.start()
        self.write("b.ts", "// one\n// two\n")
        self.assertEqual(self.hook(session_event("SessionStart", source="compact")), (0, "", ""))
        self.assertEqual(self.stop()[0], 2)

    def test_a_second_session_start_does_not_build_a_snapshot(self):
        self.start()
        with mock.patch.object(gitio, "snapshot_tree", wraps=gitio.snapshot_tree) as snapshot:
            self.assertEqual(self.hook(session_event("SessionStart", source="resume")), (0, "", ""))
        snapshot.assert_not_called()

    def test_an_unsafe_session_id_records_and_judges_nothing(self):
        self.assertEqual(self.hook(session_event("SessionStart", session_id="../x")), (0, "", ""))
        self.write("b.ts", "// one\n// two\n")
        self.assertEqual(self.hook(session_event("Stop", session_id="../x")), (0, "", ""))

    def test_a_session_id_with_a_trailing_newline_records_and_judges_nothing(self):
        self.assertEqual(self.hook(session_event("SessionStart", session_id="abc\n")), (0, "", ""))
        sessions = gitio.git_path(self.tmp, session.SESSIONS)
        self.assertEqual(os.listdir(sessions) if os.path.isdir(sessions) else [], [])
        self.write("b.ts", "// one\n// two\n")
        self.assertEqual(self.hook(session_event("Stop", session_id="abc\n")), (0, "", ""))

    def test_a_snapshot_that_fails_is_silent_and_means_no_check(self):
        with mock.patch.object(gitio, "snapshot_tree", side_effect=gitio.GitError("boom")):
            self.start()
        self.write("b.ts", "// one\n// two\n")
        self.assertEqual(self.stop(), (0, "", ""))

    def test_git_failing_at_stop_blocks(self):
        self.start()
        with mock.patch.object(gitio, "snapshot_tree", side_effect=gitio.GitError("boom")):
            self.assertEqual(self.stop()[0], 2)

    def test_any_failure_taking_the_snapshot_means_no_snapshot(self):
        with mock.patch.object(gitio, "snapshot_tree", side_effect=ValueError("x")):
            self.start()
        self.write("b.ts", "// one\n// two\n")
        self.assertEqual(self.stop(), (0, "", ""))

    def test_a_planted_snapshot_is_not_passed_to_git_as_an_option(self):
        self.start()
        planted = os.path.join(self.tmp, "planted")
        with open(os.path.join(gitio.git_path(self.tmp, session.SESSIONS), "s1"), "w", encoding="ascii") as handle:
            handle.write("--output=" + planted)
        self.write("b.ts", "// one\n// two\n")
        self.assertEqual(self.stop(), (0, "", ""))
        self.assertFalse(os.path.exists(planted))

    def test_a_snapshot_whose_tree_is_gone_means_no_snapshot(self):
        self.start()
        with open(os.path.join(gitio.git_path(self.tmp, session.SESSIONS), "s1"), "w", encoding="ascii") as handle:
            handle.write("0" * 39 + "1")
        self.write("b.ts", "// one\n// two\n")
        self.assertEqual(self.stop(), (0, "", ""))

    def test_a_subdirectory_root_reads_its_own_files(self):
        self.write("sub/a.ts", "const a = 1;\n")
        self.commit("sub")
        self.assertEqual(self.run_cli("--hook", "--root", "sub", stdin=session_event("SessionStart"))[0], 0)
        self.write("sub/a.ts", "// one\n// two\n")
        code, _out, err = self.run_cli("--hook", "--root", "sub", stdin=session_event("Stop"))
        self.assertEqual(code, 2)
        self.assertIn("a.ts:1: C1", err)

    def test_any_other_event_is_judged_as_a_write_as_before(self):
        code, out, err = self.hook(session_event("PostToolUse", tool_name="Write",
                                                 tool_input={"file_path": "b.ts", "content": "// one\n// two\n"}))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("b.ts:1: C1: 2-line prose block (limit 1)", err)

    def test_an_event_that_is_not_an_object_or_names_no_tool_is_refused(self):
        self.assertEqual(self.hook("[]")[0], 2)
        self.assertEqual(self.hook(json.dumps({"hook_event_name": 3}))[0], 2)

    def test_the_blobs_are_read_in_a_number_of_git_calls_that_does_not_grow_with_the_files(self):
        self.start()

        def git_calls(count):
            for index in range(count):
                self.write("f%d.ts" % index, "// one\n// two\n")
            with mock.patch.object(gitio, "_git_bytes", wraps=gitio._git_bytes) as git:
                self.assertEqual(self.stop()[0], 2)
            return git.call_count

        self.assertEqual(git_calls(1), git_calls(30))


class TestSessionHooksAgainstHead(Sandbox):
    """Stop judges only lines changed since the session started and not yet committed, so a moved HEAD adds none."""

    OLD = "// one\n// two\nconst a = 1;\n"

    def setUp(self):
        super().setUp()
        self.init_repo()
        self.write("a.ts", "const a = 1;\n")
        self.commit("clean")

    def hook(self, name):
        return self.run_cli("--hook", stdin=session_event(name))

    def start(self):
        self.assertEqual(self.hook("SessionStart"), (0, "", ""))

    def branch_with_old_comments(self, name):
        self.git("checkout", "-q", "-b", name)
        self.write("a.ts", self.OLD)
        self.write("old.ts", self.OLD)
        self.commit("old comments")
        self.git("checkout", "-q", "-")

    def test_checking_out_a_branch_with_old_comments_does_not_block(self):
        self.branch_with_old_comments("release")
        self.start()
        self.git("checkout", "-q", "release")
        self.assertEqual(self.hook("Stop"), (0, "", ""))

    def test_a_hard_reset_to_an_older_commit_with_old_comments_does_not_block(self):
        self.write("a.ts", self.OLD)
        old = self.commit("old comments")
        self.write("a.ts", "const a = 1;\n")
        self.commit("clean them")
        self.start()
        self.git("reset", "-q", "--hard", old)
        self.assertEqual(self.hook("Stop"), (0, "", ""))

    def test_a_fast_forward_merge_of_old_comments_does_not_block(self):
        self.branch_with_old_comments("feature")
        self.start()
        self.git("merge", "-q", "--ff-only", "feature")
        self.assertEqual(self.hook("Stop"), (0, "", ""))

    def test_a_violation_written_after_a_checkout_still_blocks(self):
        self.branch_with_old_comments("release")
        self.start()
        self.git("checkout", "-q", "release")
        self.write("old.ts", self.OLD + "// three\n// four\n")
        code, _out, err = self.hook("Stop")
        self.assertEqual(code, 2)
        self.assertIn("old.ts:4: C1:", err)
        self.assertNotIn("old.ts:1:", err)
        self.assertNotIn("a.ts:1:", err)

    def test_a_violation_the_session_commits_is_left_to_pre_commit_and_ci(self):
        self.start()
        self.write("b.ts", self.OLD)
        self.commit("the session commits its own violation")
        self.assertEqual(self.hook("Stop"), (0, "", ""))

    def test_a_merge_conflict_in_a_file_the_policy_does_not_cover_does_not_block(self):
        self.write("a.md", "base\n")
        self.commit("notes")
        self.git("checkout", "-q", "-b", "other")
        self.write("a.md", "other\n")
        self.commit("their notes")
        self.git("checkout", "-q", "-")
        self.write("a.md", "mine\n")
        self.commit("my notes")
        self.start()
        subprocess.run(("git", "merge", "-q", "other"), cwd=self.tmp, capture_output=True)
        self.assertIn("a.md", self.git("ls-files", "-u").stdout)
        self.assertEqual(self.hook("Stop"), (0, "", ""))

    def conflicting_branch(self):
        """Branch `other` changes a.md as the current branch does, and adds old.ts with an old comment."""
        self.write("a.md", "base\n")
        self.commit("notes")
        self.git("checkout", "-q", "-b", "other")
        self.write("a.md", "other\n")
        self.write("old.ts", self.OLD)
        self.commit("their notes and an old comment")
        self.git("checkout", "-q", "-")
        self.write("a.md", "mine\n")
        self.commit("my notes")
        return self.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def stopped_on_a_conflict(self, *command):
        subprocess.run(("git",) + command, cwd=self.tmp, capture_output=True)
        self.assertIn("a.md", self.git("ls-files", "-u").stdout)

    def test_a_merge_stopped_on_a_conflict_brings_in_no_old_line(self):
        self.conflicting_branch()
        self.start()
        self.stopped_on_a_conflict("merge", "other")
        self.assertEqual(self.hook("Stop"), (0, "", ""))

    def test_a_cherry_pick_stopped_on_a_conflict_brings_in_no_old_line(self):
        self.conflicting_branch()
        self.start()
        self.stopped_on_a_conflict("cherry-pick", "other")
        self.assertEqual(self.hook("Stop"), (0, "", ""))

    def test_a_rebase_stopped_on_a_conflict_brings_in_no_old_line(self):
        main = self.conflicting_branch()
        self.start()
        self.git("checkout", "-q", "other")
        self.stopped_on_a_conflict("rebase", main)
        self.assertEqual(self.hook("Stop"), (0, "", ""))

    def test_a_merge_with_no_commit_brings_in_no_old_line(self):
        self.write("a.md", "base\n")
        self.commit("notes")
        self.git("checkout", "-q", "-b", "other")
        self.write("old.ts", self.OLD)
        self.commit("an old comment")
        self.git("checkout", "-q", "-")
        self.write("a.md", "mine\n")
        self.commit("my notes")
        self.start()
        self.git("merge", "-q", "--no-commit", "other")
        self.assertEqual(self.hook("Stop"), (0, "", ""))

    def test_a_line_the_session_writes_mid_merge_still_blocks(self):
        self.conflicting_branch()
        self.start()
        self.stopped_on_a_conflict("merge", "other")
        self.write("old.ts", self.OLD + "// three\n// four\n")
        code, _out, err = self.hook("Stop")
        self.assertEqual(code, 2)
        self.assertIn("old.ts:4: C1:", err)
        self.assertNotIn("old.ts:1:", err)

    def test_a_line_the_session_reverts_to_its_committed_text_is_not_judged(self):
        self.write("a.ts", "// one\n// two\nconst a = 1;\n")
        self.commit("an old block")
        self.write("a.ts", "// one\nconst b = 0;\nconst a = 1;\n")
        self.start()
        self.write("a.ts", "// one\n// two\nconst a = 2;\n")
        self.assertEqual(self.hook("Stop"), (0, "", ""))


class TestAnEntryNamedHead(Sandbox):
    """A root entry named like a revision must not make git read a revision as a path, or refuse it as ambiguous."""

    def setUp(self):
        super().setUp()
        self.init_repo()
        self.write("HEAD/a.ts", "const a = 1;\n")
        self.base = self.commit("a directory named HEAD")

    def hook(self, name):
        return self.run_cli("--hook", stdin=session_event(name))

    def test_a_stop_with_nothing_changed_is_clean(self):
        self.assertEqual(self.hook("SessionStart"), (0, "", ""))
        self.assertEqual(self.hook("Stop"), (0, "", ""))

    def test_a_violation_the_session_writes_still_blocks(self):
        self.assertEqual(self.hook("SessionStart"), (0, "", ""))
        self.write("HEAD/b.ts", "// one\n// two\n")
        code, out, err = self.hook("Stop")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("HEAD/b.ts:1: C1: 2-line prose block (limit 1)", err)

    def test_diff_and_staged_judge_the_lines_they_select(self):
        self.write("HEAD/a.ts", "const a = 1;\n// one\n// two\n")
        self.commit("add a block")
        code, out, err = self.run_cli("--diff", self.base)
        self.assertEqual((code, out.splitlines()[0], err), (1, "HEAD/a.ts:2: C1: 2-line prose block (limit 1)", ""))
        self.write("HEAD/b.ts", "// three\n// four\n")
        self.git("add", "HEAD/b.ts")
        code, out, err = self.run_cli("--staged")
        self.assertEqual((code, out.splitlines()[0], err), (1, "HEAD/b.ts:1: C1: 2-line prose block (limit 1)", ""))


class TestSessionHooksBeforeTheFirstCommit(Sandbox):
    def test_a_new_violating_file_blocks_the_stop(self):
        self.init_repo()
        self.assertEqual(self.run_cli("--hook", stdin=session_event("SessionStart")), (0, "", ""))
        self.write("b.ts", "// one\n// two\n")
        self.assertEqual(self.run_cli("--hook", stdin=session_event("Stop"))[0], 2)


class TestSessionHooksOutsideGit(Sandbox):
    def test_outside_a_repository_the_session_ends_normally(self):
        self.assertEqual(self.run_cli("--hook", stdin=session_event("SessionStart")), (0, "", ""))
        self.write("b.ts", "// one\n// two\n")
        self.assertEqual(self.run_cli("--hook", stdin=session_event("Stop")), (0, "", ""))

    def test_in_a_repository_git_cannot_read_there_is_no_snapshot_so_the_session_ends(self):
        self.write(".git", "gitdir: %s\n" % os.path.join(self.tmp, "missing"))
        self.assertEqual(self.run_cli("--hook", stdin=session_event("SessionStart")), (0, "", ""))
        self.write("b.ts", "// one\n// two\n")
        self.assertEqual(self.run_cli("--hook", stdin=session_event("Stop")), (0, "", ""))
