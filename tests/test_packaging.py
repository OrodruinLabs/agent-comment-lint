"""The files each install channel reads: one version everywhere, and a hook wrapper that only ever blocks with 2."""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

from agent_comment_lint import __version__, governance
from test_agents import fixture

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


GUARD = os.path.join(REPO, "integrations", "guard", "agent-comment-lint-guard")
CAPTURE = os.path.join(REPO, "integrations", "capture", "capture-event")
NOT_INSTALLED = b"Blocked: agent-comment-lint is not installed."


def fake_command(tmp, body):
    """A fake `agent-comment-lint` in `tmp`: a `.cmd` on Windows, a `#!/bin/sh` script elsewhere."""
    if os.name != "nt":
        fake_bin(tmp, **{"agent-comment-lint": body})
        return
    with open(os.path.join(tmp, "agent-comment-lint.cmd"), "w", encoding="utf-8", newline="\r\n") as handle:
        handle.write("@echo off\r\n%s\r\n" % body)


def script_command(name):
    """The command line that runs a `.sh` script under the POSIX shell, or a `.cmd` one under cmd on Windows."""
    return ["cmd", "/c", name + ".cmd"] if os.name == "nt" else [SHELL, name + ".sh"]


def exit_body(code):
    return "exit /b %d" % code if os.name == "nt" else "exit %d" % code


def save_stdin_body(path):
    """Fake body that writes its standard input to `path`; `findstr` copies every line on Windows."""
    return 'findstr "^" > "%s"' % path if os.name == "nt" else 'cat > "%s"' % path


@unittest.skipUnless(SHELL, "no POSIX shell on PATH")
class TestGuards(unittest.TestCase):
    def run_guard(self, body, stdin=b"", agent="claude", in_cwd=False):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = os.path.join(tmp, "bin")
            os.mkdir(bin_dir)
            if body is not None and not in_cwd:
                fake_command(bin_dir, body.replace("{tmp}", tmp))
            if in_cwd:
                work = os.path.join(tmp, "work")
                os.mkdir(work)
                fake_command(work, body)
            # The test PATH drops every directory that holds a real install, so a missing command stays missing.
            kept = [entry for entry in os.environ["PATH"].split(os.pathsep)
                    if entry and not shutil.which("agent-comment-lint", path=entry)]
            env = dict(os.environ, PATH=os.pathsep.join([bin_dir] + kept))
            done = subprocess.run(script_command(GUARD) + [agent], input=stdin, capture_output=True, env=env,
                                  cwd=os.path.join(tmp, "work") if in_cwd else None)
            done.saved = {}
            for name in os.listdir(tmp):
                if name not in ("bin", "work"):
                    with open(os.path.join(tmp, name), "rb") as handle:
                        done.saved[name] = handle.read().replace(b"\r\n", b"\n")
            return done

    def test_the_guards_keep_their_line_endings_on_every_checkout(self):
        with open(os.path.join(REPO, ".gitattributes"), encoding="utf-8") as handle:
            rules = [line.split() for line in handle.read().splitlines()]
        self.assertIn(["*.cmd", "text", "eol=crlf"], rules)
        for name in (GUARD, CAPTURE):
            with open(name + ".cmd", "rb") as handle:
                self.assertIn(b"\r\n", handle.read())
            with open(name + ".sh", "rb") as handle:
                self.assertNotIn(b"\r", handle.read())

    def test_a_missing_command_is_blocked_with_two(self):
        done = self.run_guard(None)
        self.assertEqual(done.returncode, 2)
        self.assertIn(NOT_INSTALLED, done.stderr)

    def test_a_clean_verdict_passes(self):
        self.assertEqual(self.run_guard(exit_body(0)).returncode, 0)

    def test_a_violation_verdict_is_blocked_with_two(self):
        self.assertEqual(self.run_guard(exit_body(1)).returncode, 2)

    @unittest.skipUnless(os.name == "nt", "a negative exit code is a Windows crash code")
    def test_a_negative_exit_code_is_blocked_with_two(self):
        self.assertEqual(self.run_guard("exit /b -1").returncode, 2)

    @unittest.skipUnless(os.name == "nt", "only cmd looks in the working directory before PATH")
    def test_a_command_in_the_working_directory_is_not_run(self):
        done = self.run_guard(exit_body(0), in_cwd=True)
        self.assertEqual(done.returncode, 2)
        self.assertIn(NOT_INSTALLED, done.stderr)

    def test_a_could_not_scan_verdict_stays_two(self):
        self.assertEqual(self.run_guard(exit_body(2)).returncode, 2)

    def test_the_command_receives_standard_input_unchanged(self):
        done = self.run_guard(save_stdin_body("{tmp}" + os.sep + "stdin.txt") + "\n" + exit_body(0), b'{"a": 1}\n')
        self.assertEqual(done.saved["stdin.txt"], b'{"a": 1}\n')

    def test_the_command_is_told_the_hook_mode_and_the_agent(self):
        echo = "echo %*" if os.name == "nt" else 'echo "$@"'
        done = self.run_guard("%s > {tmp}%sargs.txt\n%s" % (echo, os.sep, exit_body(0)), agent="copilot")
        self.assertEqual(done.saved["args.txt"].split(), [b"--hook", b"--agent", b"copilot"])


@unittest.skipUnless(SHELL, "no POSIX shell on PATH")
class TestCapture(unittest.TestCase):
    def run_capture(self, stdin, capture):
        env = dict(os.environ)
        env.pop("AGENT_COMMENT_LINT_CAPTURE", None)
        if capture is not None:
            env["AGENT_COMMENT_LINT_CAPTURE"] = capture
        return subprocess.run(script_command(CAPTURE), input=stdin, capture_output=True, env=env)

    def captured(self, events):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "events.jsonl")
            for event in events:
                self.assertEqual(self.run_capture(event, target).returncode, 0)
            with open(target, "rb") as handle:
                return handle.read()

    def test_stdin_and_a_newline_are_appended(self):
        self.assertEqual(self.captured([b'{"a": 1}', b'{"b": 2}']), b'{"a": 1}\n{"b": 2}\n')

    def test_a_long_single_line_is_copied_byte_for_byte(self):
        event = b'{"content": "' + b"x" * 100000 + b'"}'
        self.assertEqual(self.captured([event]), event + b"\n")

    def test_an_unset_file_says_so_and_appends_nothing(self):
        for capture in (None, ""):
            done = self.run_capture(b"{}", capture)
            self.assertEqual(done.returncode, 0)
            self.assertIn(b"AGENT_COMMENT_LINT_CAPTURE", done.stderr)


CODEX_HOOKS = os.path.join(REPO, "integrations", "codex", "hooks.json")


class TestCodexTemplate(unittest.TestCase):
    """The Codex template installed as `.codex/hooks.json` with the guards beside it, run the way Codex runs a hook."""

    def handler(self):
        groups = load("integrations", "codex", "hooks.json")["hooks"]["PreToolUse"]
        self.assertEqual([group["matcher"] for group in groups], ["^apply_patch$"])
        (handler,) = groups[0]["hooks"]
        return handler

    def test_both_commands_run_the_guard_for_codex(self):
        handler = self.handler()
        self.assertEqual(handler["type"], "command")
        self.assertNotIn("async", handler)
        self.assertIn('/.codex/agent-comment-lint-guard.sh" codex', handler["command"])
        self.assertIn('/.codex/agent-comment-lint-guard.cmd" codex', handler["commandWindows"])

    def run_hook(self, patch, guards=(".sh", ".cmd"), in_git=True):
        """Codex runs `$SHELL -lc command`, or `%COMSPEC% /C "commandWindows"`, in the session's directory."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(os.path.realpath(tmp), "repo")
            session = os.path.join(repo, "src")
            os.makedirs(os.path.join(repo, ".codex"))
            os.mkdir(session)
            if in_git:
                subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            shutil.copy(CODEX_HOOKS, os.path.join(repo, ".codex"))
            for suffix in guards:
                shutil.copy(GUARD + suffix, os.path.join(repo, ".codex"))
            bin_dir = os.path.join(tmp, "bin")
            os.mkdir(bin_dir)
            arguments = "%*" if os.name == "nt" else '"$@"'
            fake_command(bin_dir, '"%s" -m agent_comment_lint %s' % (sys.executable, arguments))
            env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"], PYTHONPATH=REPO,
                       GIT_CEILING_DIRECTORIES=os.path.realpath(tmp))
            event = dict(fixture("codex-write"), cwd=session, tool_input={"command": patch})
            if os.name == "nt":
                command = 'cmd /C "%s"' % self.handler()["commandWindows"]
            else:
                command = [SHELL, "-c", self.handler()["command"]]
            return subprocess.run(command, input=json.dumps(event).encode("utf-8"), cwd=session, env=env,
                                  capture_output=True)

    @unittest.skipUnless(SHELL or os.name == "nt", "no POSIX shell on PATH")
    def test_a_patch_adding_a_two_line_comment_is_blocked_from_a_subdirectory(self):
        done = self.run_hook("*** Begin Patch\n*** Add File: dirty.ts\n+// one\n+// two\n*** End Patch")
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn(b"src/dirty.ts:1: C1: 2-line prose block (limit 1)", done.stderr)

    @unittest.skipUnless(SHELL or os.name == "nt", "no POSIX shell on PATH")
    def test_a_clean_patch_passes_silently(self):
        done = self.run_hook("*** Begin Patch\n*** Add File: clean.ts\n+const a = 1;\n*** End Patch")
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b"", b""))

    @unittest.skipUnless(SHELL or os.name == "nt", "no POSIX shell on PATH")
    def test_a_missing_guard_is_blocked_with_two_and_a_reason(self):
        done = self.run_hook("*** Begin Patch\n*** Add File: clean.ts\n+const a = 1;\n*** End Patch", guards=())
        self.assertEqual(done.returncode, 2)
        self.assertNotEqual(done.stderr.strip(), b"")

    @unittest.skipUnless(SHELL or os.name == "nt", "no POSIX shell on PATH")
    def test_a_session_outside_a_git_work_tree_is_blocked_with_two_and_a_reason(self):
        done = self.run_hook("*** Begin Patch\n*** Add File: clean.ts\n+const a = 1;\n*** End Patch", in_git=False)
        self.assertEqual(done.returncode, 2)
        self.assertNotEqual(done.stderr.strip(), b"")


WINDSURF_HOOKS = os.path.join(REPO, "integrations", "windsurf", "hooks.json")
WINDSURF_WRITE = "windsurf-write"


class TestWindsurfTemplate(unittest.TestCase):
    """The Windsurf template installed as `.devin/hooks.json` with the guards beside it, run from the workspace root."""

    def handler(self):
        groups = load("integrations", "windsurf", "hooks.json")["hooks"]
        self.assertEqual(list(groups), ["pre_write_code"])
        (handler,) = groups["pre_write_code"]
        return handler

    def test_both_commands_run_the_guard_for_windsurf(self):
        handler = self.handler()
        self.assertTrue(handler["show_output"])
        self.assertIn(".devin/agent-comment-lint-guard.sh windsurf", handler["command"])
        self.assertIn("agent-comment-lint-guard.cmd", handler["powershell"])
        self.assertIn("windsurf", handler["powershell"])

    def run_hook(self, new_string, guards=(".sh", ".cmd"), profile=""):
        """Cascade runs `bash -c command`, or `powershell -Command powershell`, in the workspace root."""
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(os.path.realpath(tmp), "repo")
            os.makedirs(os.path.join(root, ".devin"))
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            shutil.copy(WINDSURF_HOOKS, os.path.join(root, ".devin"))
            for suffix in guards:
                shutil.copy(GUARD + suffix, os.path.join(root, ".devin"))
            bin_dir = os.path.join(tmp, "bin")
            os.mkdir(bin_dir)
            arguments = "%*" if os.name == "nt" else '"$@"'
            fake_command(bin_dir, '"%s" -m agent_comment_lint %s' % (sys.executable, arguments))
            env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"], PYTHONPATH=REPO,
                       GIT_CEILING_DIRECTORIES=os.path.realpath(tmp))
            event = fixture(WINDSURF_WRITE)
            event["tool_info"] = {"file_path": os.path.join(root, "dirty.ts"),
                                  "edits": [{"old_string": "", "new_string": new_string}]}
            if os.name == "nt":
                command = ["powershell", "-NoProfile", "-Command", profile + self.handler()["powershell"]]
            else:
                command = [BASH, "-c", self.handler()["command"]]
            return subprocess.run(command, input=json.dumps(event).encode("utf-8"), cwd=root, env=env,
                                  capture_output=True)

    @unittest.skipUnless(BASH or os.name == "nt", "no POSIX shell on PATH")
    def test_a_write_adding_a_two_line_comment_is_blocked(self):
        done = self.run_hook("// one\n// two\n")
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn(b"dirty.ts:1: C1: 2-line prose block (limit 1)", done.stderr)

    @unittest.skipUnless(BASH or os.name == "nt", "no POSIX shell on PATH")
    def test_a_clean_write_passes_silently(self):
        done = self.run_hook("const a = 1;\n")
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b"", b""))

    @unittest.skipUnless(BASH or os.name == "nt", "no POSIX shell on PATH")
    def test_a_missing_guard_is_blocked_with_two_and_a_reason(self):
        done = self.run_hook("const a = 1;\n", guards=())
        self.assertEqual(done.returncode, 2)
        self.assertNotEqual(done.stderr.strip(), b"")

    @unittest.skipUnless(os.name == "nt", "only the PowerShell form reads an exit code a profile left behind")
    def test_a_missing_guard_is_blocked_after_a_profile_ran_a_native_command(self):
        done = self.run_hook("const a = 1;\n", guards=(), profile="cmd /c exit 0; ")
        self.assertEqual(done.returncode, 2)
        self.assertIn(b"guard is missing", done.stderr)


GEMINI_POSIX = os.path.join(REPO, "integrations", "gemini", "settings.json")
GEMINI_WINDOWS = os.path.join(REPO, "integrations", "gemini", "settings.windows.json")


class TestGeminiTemplate(unittest.TestCase):
    """The Gemini templates as `.gemini/settings.json` with the guards beside it, run the way Gemini runs them."""

    def handler(self, name):
        groups = load("integrations", "gemini", name)["hooks"]
        self.assertEqual(list(groups), ["BeforeTool"])
        (group,) = groups["BeforeTool"]
        for tool in ("write_file", "replace"):
            self.assertRegex(tool, group["matcher"])
        for tool in ("read_file", "write_file_x", "run_shell_command"):
            self.assertNotRegex(tool, group["matcher"])
        (handler,) = group["hooks"]
        self.assertEqual((handler["name"], handler["type"]), ("agent-comment-lint", "command"))
        return handler

    def test_both_commands_run_the_guard_for_gemini_from_the_project_directory(self):
        self.assertIn("$GEMINI_PROJECT_DIR/.gemini/agent-comment-lint-guard.sh gemini",
                      self.handler("settings.json")["command"])
        windows = self.handler("settings.windows.json")["command"]
        self.assertIn("$GEMINI_PROJECT_DIR", windows)
        self.assertIn("agent-comment-lint-guard.cmd", windows)
        self.assertIn("gemini", windows)

    def run_hook(self, windows, new_string, guards=(".sh", ".cmd")):
        """Gemini rewrites `$GEMINI_PROJECT_DIR` quoted for the shell, then runs `bash -c` or `powershell -Command`."""
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(os.path.realpath(tmp), "repo with space")
            os.makedirs(os.path.join(root, ".gemini"))
            for suffix in guards:
                shutil.copy(GUARD + suffix, os.path.join(root, ".gemini"))
            bin_dir = os.path.join(tmp, "bin")
            os.mkdir(bin_dir)
            arguments = "%*" if os.name == "nt" else '"$@"'
            fake_command(bin_dir, '"%s" -m agent_comment_lint %s' % (sys.executable, arguments))
            env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"], PYTHONPATH=REPO)
            event = fixture("gemini-write")
            event["cwd"] = root
            event["tool_input"] = {"file_path": os.path.join(root, "dirty.ts"), "content": new_string}
            if windows:
                quoted = "'%s'" % root.replace("'", "''")
                command = self.handler("settings.windows.json")["command"].replace("$GEMINI_PROJECT_DIR", quoted)
                command = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                           command + "; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }"]
            else:
                command = self.handler("settings.json")["command"].replace("$GEMINI_PROJECT_DIR", shlex.quote(root))
                command = [BASH, "-c", command]
            return subprocess.run(command, input=json.dumps(event).encode("utf-8"), cwd=root, env=env,
                                  capture_output=True)

    def forms(self):
        # Gemini never runs the POSIX form on Windows, and Git's bash there cannot find the `.cmd` fake command.
        if BASH and os.name != "nt":
            yield False
        if os.name == "nt":
            yield True

    def test_a_write_adding_a_two_line_comment_is_blocked(self):
        for windows in self.forms():
            done = self.run_hook(windows, "// one\n// two\n")
            self.assertEqual(done.returncode, 2, done.stderr)
            self.assertIn(b"dirty.ts:1: C1: 2-line prose block (limit 1)", done.stderr)

    def test_a_clean_write_passes_silently(self):
        for windows in self.forms():
            done = self.run_hook(windows, "const a = 1;\n")
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b"", b""))

    def test_a_missing_guard_is_blocked_with_two_and_a_reason(self):
        for windows in self.forms():
            done = self.run_hook(windows, "const a = 1;\n", guards=())
            self.assertEqual(done.returncode, 2)
            self.assertNotEqual(done.stderr.strip(), b"")
