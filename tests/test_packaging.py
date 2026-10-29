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
# On Windows the first `bash` on PATH is often the WSL launcher, so the bash beside Git's `sh` is the one Actions runs.
BASH = os.path.join(os.path.dirname(SHELL), "bash.exe") if os.name == "nt" and SHELL else shutil.which("bash")


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

    def test_the_session_hooks_run_the_wrapper_and_carry_no_on_failure(self):
        hooks = load("hooks", "hooks.json")["hooks"]
        wrapper = "${CLAUDE_PLUGIN_ROOT}/hooks/agent-comment-lint-hook.sh"
        for event in ("SessionStart", "Stop"):
            commands = [hook for entry in hooks[event] for hook in entry["hooks"]]
            self.assertTrue(any(wrapper in hook["command"] for hook in commands), event)
            self.assertFalse(any("onFailure" in hook for hook in commands), event)
        self.assertEqual([entry["matcher"] for entry in hooks["PreToolUse"]], ["Write|Edit|MultiEdit"])

    def test_session_start_adds_two_lines_of_static_guidance(self):
        commands = [hook["command"] for entry in load("hooks", "hooks.json")["hooks"]["SessionStart"]
                    for hook in entry["hooks"]]
        self.assertIn('cat "${CLAUDE_PLUGIN_ROOT}/hooks/session-guidance.txt"', commands)
        with open(os.path.join(REPO, "hooks", "session-guidance.txt"), "rb") as handle:
            self.assertEqual(handle.read(),
                             b"Comments here are at most one line and say why the code is the way it is.\n"
                             b"Notes for reviewers go in the commit message or the PR description, not in code.\n")


class TestVersionPins(unittest.TestCase):
    def test_every_version_pin_in_the_docs_and_schema_is_the_package_version(self):
        pin = re.compile(r"(?:v|==)(\d+\.\d+\.\d+)")
        found = 0
        for parts in (("README.md",), ("docs", "reference.md"), ("schema", "agent-comment-lint.schema.json")):
            with open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
                lines = [line for line in handle.read().splitlines() if "devicon@" not in line]
                for version in pin.findall("\n".join(lines)):
                    found += 1
                    self.assertEqual(version, __version__, "/".join(parts))
        self.assertGreater(found, 0)
        schema_id = load("schema", "agent-comment-lint.schema.json")["$id"]
        self.assertIn("v" + __version__, schema_id)


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

    def test_the_wrapper_keeps_unix_line_endings_on_every_checkout(self):
        with open(WRAPPER, "rb") as handle:
            self.assertNotIn(b"\r", handle.read())
        with open(os.path.join(REPO, ".gitattributes"), encoding="utf-8") as handle:
            rules = [line.split() for line in handle.read().splitlines()]
        self.assertIn(["*.sh", "text", "eol=lf"], rules)
        self.assertIn(["*.txt", "text", "eol=lf"], rules)

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
        self.assertIn(b"AGENT_COMMENT_LINT_PYTHON=no-such-python-3", done.stderr)

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

    def test_the_py_launcher_is_the_last_resort(self):
        with tempfile.TemporaryDirectory() as tmp:
            launcher = '[ "$1" = "-3" ] || exit 1; shift; exec "%s" "$@"' % sys.executable
            bin_dir = fake_bin(tmp, python3="exit 1", python="exit 1", py=launcher)
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
        command = [BASH, "--noprofile", "--norc", "-eo", "pipefail", "-c", self.action_block()]
        return subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True, encoding="utf-8")

    @unittest.skipUnless(BASH and os.path.isfile(BASH) and shutil.which("git"), "needs bash and git")
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


class TestStdioEncoding(unittest.TestCase):
    def run_script(self, *args, stdin=None, cwd=None):
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        script = os.path.join(REPO, "check-agent-comment-lint.py")
        return subprocess.run([sys.executable, script, *args], input=stdin, cwd=cwd, env=env, capture_output=True)

    def test_a_non_ascii_path_is_printed_as_utf8_whatever_the_console_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, "src"))
            with open(os.path.join(tmp, "src", "\u65e5\u672c.ts"), "w", encoding="utf-8", newline="\n") as handle:
                handle.write("// one\n// two\n")
            done = self.run_script("--all", cwd=tmp)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("src/\u65e5\u672c.ts:1: C1:", done.stdout.decode("utf-8"))
        self.assertNotIn(b"Traceback", done.stderr)

    def test_a_non_ascii_excerpt_in_hook_mode_is_utf8_whatever_the_console_encoding(self):
        comment = "// " + "\u65e5" * 130
        content = comment + "\n// two\n"
        event = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "x.ts", "content": content}})
        with tempfile.TemporaryDirectory() as tmp:
            done = self.run_script("--hook", stdin=event.encode("utf-8"), cwd=tmp)
        self.assertEqual(done.returncode, 2)
        self.assertIn(("    // " + "\u65e5" * 50)[:20], done.stderr.decode("utf-8"))
        self.assertIn("\u2026", done.stderr.decode("utf-8"))
        self.assertNotIn(b"Traceback", done.stderr)


class TestRelease(unittest.TestCase):
    def test_a_release_publishes_to_pypi_through_trusted_publishing(self):
        with open(os.path.join(REPO, ".github", "workflows", "release.yml"), encoding="utf-8") as handle:
            text = handle.read()
        for expected in ("environment: pypi", "id-token: write", "pypa/gh-action-pypi-publish@release/v1",
                         "actions/upload-artifact@v4", "actions/download-artifact@v4"):
            self.assertIn(expected, text)


class TestPreCommitHooks(unittest.TestCase):
    def test_the_staged_id_judges_only_staged_lines_and_matches_the_whole_file_id_on_files(self):
        with open(os.path.join(REPO, ".pre-commit-hooks.yaml"), encoding="utf-8") as handle:
            text = handle.read()
        for expected in ("- id: agent-comment-lint-staged", "entry: agent-comment-lint --staged",
                         "pass_filenames: false"):
            self.assertIn(expected, text)
        patterns = re.findall(r"^  files: .*$", text, re.MULTILINE)
        self.assertEqual(len(patterns), 2)
        self.assertEqual(patterns[0], patterns[1])


class TestSchema(unittest.TestCase):
    def test_the_schema_names_exactly_the_packs_the_code_knows(self):
        schema = load("schema", "agent-comment-lint.schema.json")
        packs = schema["properties"]["governance"]["properties"]["packs"]["items"]["enum"]
        self.assertEqual(sorted(packs), sorted(governance.PACKS))
        self.assertFalse(schema["additionalProperties"])
