"""The files each install channel reads: one version everywhere, and a hook wrapper that only ever blocks with 2."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from agent_comment_lint import __version__

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAPPER = os.path.join(REPO, "hooks", "agent-comment-lint-hook.sh")
DIRTY = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "x.ts", "content": "// one\n// two\n"}})
CLEAN = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "x.ts", "content": "const a = 1;\n"}})
SHELL = shutil.which("sh") or shutil.which("bash")


def load(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
        return json.load(handle)


class TestManifests(unittest.TestCase):
    def test_the_plugin_names_the_package_version(self):
        self.assertEqual(load(".claude-plugin", "plugin.json")["version"], __version__)

    def test_pyproject_takes_its_version_from_the_package(self):
        with open(os.path.join(REPO, "pyproject.toml"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertRegex(text, r'version = \{ attr = "agent_comment_lint.__version__" \}')
        self.assertRegex(text, r'agent-comment-lint = "agent_comment_lint.cli:main"')

    def test_the_marketplace_offers_the_plugin_from_the_repository_root(self):
        plugin = load(".claude-plugin", "marketplace.json")["plugins"][0]
        self.assertEqual((plugin["name"], plugin["source"]), ("agent-comment-lint", "."))

    def test_the_plugin_hook_runs_the_wrapper_and_blocks_on_failure(self):
        entry = load("hooks", "hooks.json")["hooks"]["PreToolUse"][0]
        command = entry["hooks"][0]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/agent-comment-lint-hook.sh", command["command"])
        self.assertEqual(command["onFailure"], "block")
        self.assertTrue(re.fullmatch(entry["matcher"], "Edit") and re.fullmatch(entry["matcher"], "Write"))


def fake_bin(tmp, **scripts):
    """A directory holding one executable `#!/bin/sh` script per keyword, named after it."""
    for name, body in scripts.items():
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("#!/bin/sh\n%s\n" % body)
        os.chmod(path, 0o755)
    return tmp


@unittest.skipUnless(SHELL, "no POSIX shell on PATH")
class TestHookWrapper(unittest.TestCase):
    def run_wrapper(self, stdin, **environment):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, CLAUDE_PROJECT_DIR=os.path.realpath(tmp), AGENT_COMMENT_LINT_PYTHON=sys.executable)
            env.update(environment)
            if env["AGENT_COMMENT_LINT_PYTHON"] == "":
                del env["AGENT_COMMENT_LINT_PYTHON"]
            return subprocess.run([SHELL, WRAPPER], input=stdin.encode("utf-8"), capture_output=True, env=env)

    def test_a_clean_write_passes_silently(self):
        done = self.run_wrapper(CLEAN)
        self.assertEqual((done.returncode, done.stderr), (0, b""))

    def test_a_dirty_write_is_blocked_with_two(self):
        done = self.run_wrapper(DIRTY)
        self.assertEqual(done.returncode, 2)
        self.assertIn(b"x.ts:1: C1: 2-line prose block (limit 1)", done.stderr)

    def test_a_missing_interpreter_is_blocked_with_two(self):
        done = self.run_wrapper(CLEAN, AGENT_COMMENT_LINT_PYTHON="no-such-python-3")
        self.assertEqual(done.returncode, 2)
        self.assertIn(b"Blocked:", done.stderr)

    def test_a_project_directory_that_does_not_exist_is_blocked_with_two(self):
        done = self.run_wrapper(CLEAN, CLAUDE_PROJECT_DIR="/no/such/directory")
        self.assertEqual(done.returncode, 2)

    def test_an_interpreter_older_than_3_9_is_passed_over_for_the_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = fake_bin(tmp, python3="exit 1", python='exec "%s" "$@"' % sys.executable)
            done = self.run_wrapper(DIRTY, AGENT_COMMENT_LINT_PYTHON="",
                                    PATH=bin_dir + os.pathsep + os.environ["PATH"])
        self.assertEqual(done.returncode, 2)
        self.assertIn(b"x.ts:1: C1: 2-line prose block (limit 1)", done.stderr)

    def test_no_usable_interpreter_is_blocked_with_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = fake_bin(tmp, python3="exit 1", python="exit 1", py="exit 1")
            done = self.run_wrapper(CLEAN, AGENT_COMMENT_LINT_PYTHON="",
                                    PATH=bin_dir + os.pathsep + os.environ["PATH"])
        self.assertEqual(done.returncode, 2)
        self.assertIn(b"Blocked: agent-comment-lint needs Python 3.9 or newer on PATH.", done.stderr)
