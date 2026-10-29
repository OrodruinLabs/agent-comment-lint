"""The files each install channel reads: one version everywhere, and a hook wrapper that only ever blocks with 2."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from agent_comment_lint import __version__, governance

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


class TestAction(unittest.TestCase):
    def matcher(self):
        return re.compile(load(".github", "problem-matcher.json")["problemMatcher"][0]["pattern"][0]["regexp"])

    def test_the_problem_matcher_reads_findings_and_nothing_else(self):
        hit = self.matcher().match("src/a.ts:12: C1: 3-line prose block (limit 1)")
        self.assertEqual(hit.groups(), ("src/a.ts", "12", "C1", "3-line prose block (limit 1)"))
        for line in ("agent-comment-lint: 2 violation(s) in 1 of 57 file(s) scanned.",
                     "a.ts: could not scan: is a directory, not a file", "a.ts:3: could not scan: line 3: x"):
            self.assertIsNone(self.matcher().match(line), line)

    def test_the_action_registers_and_removes_the_matcher_and_keeps_the_exit_code(self):
        with open(os.path.join(REPO, "action.yml"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("::add-matcher::$GITHUB_ACTION_PATH/.github/problem-matcher.json", text)
        self.assertIn("::remove-matcher owner=agent-comment-lint::", text)
        self.assertIn("GITHUB_STEP_SUMMARY", text)

    def action_block(self):
        with open(os.path.join(REPO, "action.yml"), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        start = next(i for i, line in enumerate(lines) if line.strip() == "run: |") + 1
        block = []
        for line in lines[start:]:
            if line.strip() and not line.startswith(" " * 8):
                break
            block.append(line[8:])
        return "\n".join(block) + "\n"

    def run_action(self, repo, summary, base):
        env = dict(os.environ, GITHUB_ACTION_PATH=REPO, GITHUB_STEP_SUMMARY=summary, MODE="diff", BASE=base,
                   ARGS="", TARGET="")
        command = ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", self.action_block()]
        return subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True, encoding="utf-8")

    @unittest.skipUnless(shutil.which("bash") and shutil.which("git"), "needs bash and git")
    def test_the_action_prints_findings_and_removes_the_matcher_under_bash_e(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.mkdir(repo)

            def git(*args):
                return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo,
                                      check=True, capture_output=True, text=True).stdout.strip()

            git("init", "-q")
            with open(os.path.join(repo, "a.ts"), "w", encoding="utf-8", newline="\n") as handle:
                handle.write("const a = 1;\n")
            git("add", ".")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            with open(os.path.join(repo, "a.ts"), "w", encoding="utf-8", newline="\n") as handle:
                handle.write("// one\n// two\nconst a = 1;\n")
            git("commit", "-qam", "dirty")
            summary = os.path.join(tmp, "summary.md")
            done = self.run_action(repo, summary, base)
            self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
            self.assertIn("a.ts:1: C1:", done.stdout)
            self.assertIn("::remove-matcher owner=agent-comment-lint::", done.stdout)
            with open(summary, encoding="utf-8") as handle:
                self.assertIn("a.ts:1: C1:", handle.read())
            missing = self.run_action(repo, summary, "")
            self.assertEqual(missing.returncode, 2, missing.stdout + missing.stderr)
            self.assertNotIn("::add-matcher::", missing.stdout)


class TestRelease(unittest.TestCase):
    def test_a_release_publishes_to_pypi_through_trusted_publishing(self):
        with open(os.path.join(REPO, ".github", "workflows", "release.yml"), encoding="utf-8") as handle:
            text = handle.read()
        for expected in ("environment: pypi", "id-token: write", "pypa/gh-action-pypi-publish@release/v1",
                         "actions/upload-artifact@v4", "actions/download-artifact@v4"):
            self.assertIn(expected, text)


class TestSchema(unittest.TestCase):
    def test_the_schema_names_exactly_the_packs_the_code_knows(self):
        schema = load("schema", "agent-comment-lint.schema.json")
        packs = schema["properties"]["governance"]["properties"]["packs"]["items"]["enum"]
        self.assertEqual(sorted(packs), sorted(governance.PACKS))
        self.assertFalse(schema["additionalProperties"])
