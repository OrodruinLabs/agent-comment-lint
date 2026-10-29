"""The command line: choose the files, read them, hand each to the engine, print the report."""
import argparse
import json
import os
import sys

from . import __version__
from . import config as settings
from . import engine, gitio, hook, report, session
from .diff import parse_diff_ranges
from .lexers import EXTENSIONS, LexError

DESCRIPTION = "Check code comments against fixed rules. Exit 0 clean, 1 violations, 2 could not scan."
SCOPE_NOTE = "Covered file types: %s" % " ".join(EXTENSIONS)

# A byte-order mark is not part of the text: left in, it hides the first line's comment marker.
ENCODING = "utf-8-sig"
BYTE_ORDER_MARK = "\ufeff"

DIFF_MISMATCH = "git counts %d added line(s) but its diff shows %d, so the changed lines cannot be trusted"
BINARY_NOT_TEXT = "git shows no changed lines for it (a binary file) and it is not UTF-8 text, so it cannot be judged"
HOOK_INPUT = "standard input is not a Claude Code PreToolUse event: %s"
HOOK_NOT_UTF8 = "is not UTF-8 text, so the write cannot be judged"
HOOK_BLOCKED = "Blocked: agent-comment-lint rejects this write.\n"
HOOK_HEADER = HOOK_BLOCKED + report.HOOK_SCOPE
HOOK_STOP_HEADER = ("Before you finish: agent-comment-lint found comments this session added that break the policy.\n"
                    "Only lines changed since this session started are judged.\n")
STOP_CLOSING = ("Fix these comments before you finish; the check runs again when you stop.",
                report.HOOK_CLOSING[1], report.HOOK_CLOSING[2])


def _parser():
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=SCOPE_NOTE)
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--diff", metavar="BASE",
                      help="judge only the lines changed since the merge base with BASE")
    mode.add_argument("--staged", action="store_true",
                      help="judge only the lines staged for the next commit, as the index holds them")
    mode.add_argument("--all", action="store_true", help="judge every covered file in the repository")
    mode.add_argument("--files", nargs="+", metavar="PATH", help="judge the named files")
    mode.add_argument("--stdin-path", metavar="PATH",
                      help="judge the text on standard input as if it were the file PATH")
    mode.add_argument("--hook", action="store_true",
                      help="judge the write in a Claude Code PreToolUse event on standard input; exit 2 blocks it")
    parser.add_argument("--json", action="store_true", help="print one JSON document instead of text")
    parser.add_argument("--root", metavar="DIR",
                        help="repository root (default: the git top level of the working directory)")
    parser.add_argument("--config", metavar="FILE",
                        help="settings file (default: %s at the root)" % settings.CONFIG_NAME)
    return parser


class _Refused(Exception):
    """The run cannot give a verdict; `where` names the argument at fault."""

    def __init__(self, where, message):
        super().__init__(message)
        self.where = where


def _mode(args):
    """The chosen mode's name; an empty --diff value is still diff mode, so it is refused as a ref, not skipped."""
    if args.hook:
        return "hook"
    if args.all:
        return "all"
    if args.staged:
        return "staged"
    for name in ("diff", "files"):
        if getattr(args, name) is not None:
            return name
    return "stdin"


def _work_tree(directory, mode):
    """The git top level of `directory`; None where git names none and the mode can give a verdict without it."""
    try:
        return gitio.toplevel(directory)
    except gitio.GitError:
        if mode in ("diff", "staged") or (mode == "all" and gitio.claims_repository(directory)):
            raise
        return None


def _root(args, cwd, mode):
    """(root, whether git lists its files); only --all asks git about a root the caller named."""
    if not args.root:
        top = _work_tree(cwd, mode)
        return os.path.realpath(top or cwd), top is not None
    root = os.path.realpath(os.path.join(cwd, args.root))
    if not os.path.isdir(root):
        raise _Refused("--root", "%s is not a directory" % args.root)
    return root, mode == "all" and _work_tree(root, mode) is not None


def _load_config(args, root, cwd):
    """The repository's settings; a file named with --config must exist, the default one may be absent."""
    path = os.path.join(cwd, args.config) if args.config else os.path.join(root, settings.CONFIG_NAME)
    if not args.config and not os.path.exists(path):
        return settings.EMPTY
    try:
        with open(path, encoding=ENCODING) as handle:
            text = handle.read()
    except OSError as error:
        raise settings.ConfigError(error.strerror or str(error))
    except UnicodeDecodeError:
        raise settings.ConfigError("is not UTF-8 text")
    return settings.parse(text)


def _judged(config, path):
    return (engine.in_scope(path) and not settings.skipped_by_default(path)
            and not settings.excluded(config, path))


def _walked_files(root):
    """Every file under `root`, for a tree that is not a git work tree."""
    found = []
    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name not in settings.DEFAULT_SKIP_DIRS)
        for name in files:
            found.append(os.path.relpath(os.path.join(directory, name), root).replace(os.sep, "/"))
    return found


def _resolved_inside(root, directory, path):
    """The real path of `path` taken from `directory`; None when it lands outside the root."""
    resolved = os.path.realpath(os.path.join(directory, path))
    try:
        inside = os.path.normcase(os.path.commonpath([root, resolved])) == os.path.normcase(root)
    except ValueError:
        # Paths on two drives, or under a UNC root and a drive, share no part at all.
        inside = False
    return resolved if inside else None


def _relative_to_root(root, cwd, path):
    """The root-relative form of a path the caller named; None when it resolves outside the root."""
    resolved = _resolved_inside(root, cwd, path)
    return None if resolved is None else os.path.relpath(resolved, root).replace(os.sep, "/")


def _read(root, path, errors, newline=None):
    """The file's text; raises OSError for anything that is not a readable file inside the root."""
    resolved = _resolved_inside(root, root, path)
    if resolved is None:
        raise OSError(0, "resolves outside the repository root")
    if os.path.isdir(resolved):
        raise OSError(0, "is a directory, not a file")
    with open(resolved, encoding=ENCODING, errors=errors, newline=newline) as handle:
        return handle.read()


def _blob_reader(spec_prefix):
    """A reader of git blobs named `spec_prefix + path`; unlike `_read` it decodes strictly, so bad UTF-8 blocks."""
    def read(root, path, errors):
        return gitio.blob(root, spec_prefix + path).decode(ENCODING)
    return read


def _stdin_text(stdin, errors="replace"):
    """Standard input decoded as a file is, whatever the locale; a stream with no bytes behind it is taken as text."""
    raw = getattr(stdin, "buffer", None)
    if raw is not None:
        return raw.read().decode(ENCODING, errors=errors)
    text = stdin.read()
    return text[1:] if text.startswith(BYTE_ORDER_MARK) else text


class _Run:
    """Accumulates one run's results; the report is built from it once every file is judged."""

    def __init__(self, mode):
        self.mode = mode
        self.scanned = 0
        self.unresolved = 0
        self.findings = []
        self.errors = []
        self.texts = {}
        self.tool = None
        self.event = None
        self.governance = settings.EMPTY.governance

    def judge(self, path, text, ranges=None):
        try:
            result = engine.check_text(path, text, self.governance)
        except LexError as error:
            self.errors.append((path, error.line, error.message))
            return
        found = result.findings if ranges is None else engine.within(result.findings, ranges)
        if found:
            self.texts[path] = text
        self.scanned += 1
        self.unresolved += result.unresolved_lines
        self.findings.extend((path, finding) for finding in found)

    def judge_file(self, root, path, ranges=None, errors="replace", read=None):
        try:
            text = (read or _read)(root, path, errors)
        except UnicodeDecodeError:
            self.errors.append((path, None, BINARY_NOT_TEXT))
            return
        except OSError as error:
            self.errors.append((path, None, error.strerror or str(error)))
            return
        except gitio.GitError as error:
            self.errors.append((path, None, str(error)))
            return
        self.judge(path, text, ranges)

    def report(self):
        return report.Report(self.mode, self.scanned, self.findings, self.errors, self.unresolved)


def _run_all(run, root, config, listed_by_git):
    paths = gitio.listed_files(root) if listed_by_git else _walked_files(root)
    judged = [path for path in dict.fromkeys(paths)
              if _judged(config, path) and os.path.isfile(os.path.join(root, path))]
    if not judged:
        raise _Refused("--all", "no covered file under the root, so there is nothing to give a verdict on")
    for path in judged:
        run.judge_file(root, path)


def _run_diff(run, root, config, base):
    _run_changes(run, root, config, gitio.diff_span(root, base), _read)


def _run_changes(run, root, config, span, read):
    """Judge the changed lines; a file whose parsed ranges do not add up to git's own count is refused, not passed."""
    ranges = parse_diff_ranges(gitio.changed_diff(root, span))
    for path, (added, same_content) in gitio.changed_files(root, span).items():
        if same_content or not _judged(config, path):
            # A mode change or a pure rename changes no line, so the file is not read, whatever it holds.
            continue
        if added is None:
            # Git prints no lines for a file it treats as binary, so every line of it counts as changed.
            run.judge_file(root, path, errors="strict", read=read)
            continue
        spans = ranges.get(path, [])
        parsed = sum(end - start + 1 for start, end in spans)
        if parsed != added:
            run.errors.append((path, None, DIFF_MISMATCH % (added, parsed)))
            continue
        run.judge_file(root, path, spans, read=read)


def _named(run, root, cwd, config, path):
    """The root-relative path of a named file the policy judges; None when it is skipped or refused."""
    relative = _relative_to_root(root, cwd, path)
    if relative is None:
        run.errors.append((path, None, "resolves outside the repository root"))
        return None
    if os.path.isdir(os.path.join(root, relative)):
        run.errors.append((relative, None, "is a directory, not a file"))
        return None
    return relative if _judged(config, relative) else None


def _current_text(root, relative):
    """The file before the write, line endings kept so an edit's old string still matches; None when absent."""
    try:
        return _read(root, relative, "strict", newline="")
    except FileNotFoundError:
        return None


def _sibling_worktree(root, path):
    """The top of another worktree of the root's repository that holds `path`; None when there is none."""
    directory = os.path.dirname(path)
    while not os.path.isdir(directory):
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent
    try:
        if gitio.common_dir(directory) != gitio.common_dir(root):
            return None
        return os.path.realpath(gitio.toplevel(directory))
    except gitio.GitError:
        return None


def _covered_paths(root, config):
    """The paths git lists under the root that the policy judges."""
    return [path for path in dict.fromkeys(gitio.listed_files(root)) if _judged(config, path)]


def _session_directory(root, event):
    """(the snapshot directory, the session id) of a SessionStart or Stop event; None when the id is unusable."""
    session_id = event.get("session_id")
    if not isinstance(session_id, str) or not session.SESSION_ID.match(session_id):
        return None
    return gitio.git_path(root, session.SESSIONS), session_id


def _record_session(root, load_config, event):
    """Record the working tree for the session; any failure means there is no snapshot, and nothing is printed."""
    try:
        located = _session_directory(root, event)
        if located is None or _work_tree(root, "hook") is None:
            return
        config = load_config(root)
        session.record(located[0], located[1], gitio.snapshot_tree(root, _covered_paths(root, config)))
    except Exception:
        # A session start never fails because of the snapshot; the Stop check then lets the session end.
        return


def _run_session_end(run, root, load_config, event):
    """Judge the covered files that changed since the session's snapshot, on the lines that changed."""
    run.event = "Stop"
    if _work_tree(root, "all") is None:
        return
    located = _session_directory(root, event)
    if located is None:
        return
    before = session.recorded(*located)
    if before is None:
        return
    config = load_config(root)
    run.governance = config.governance
    now = gitio.snapshot_tree(root, _covered_paths(root, config))
    _run_changes(run, root, config, (before, now), _blob_reader(now + ":./"))


def _run_hook(run, root, cwd, load_config, stdin, follow_worktrees):
    """Judge the whole file a proposed write would leave, on the lines the write adds or changes."""
    try:
        event = json.loads(_stdin_text(stdin, errors="strict"))
        name = event.get("hook_event_name", "PreToolUse") if isinstance(event, dict) else "PreToolUse"
        if not isinstance(name, str):
            raise hook.HookInputError("\"hook_event_name\" is not a string")
        target = hook.target(event) if name == "PreToolUse" else None
    except (ValueError, hook.HookInputError) as error:
        raise _Refused("--hook", HOOK_INPUT % error)
    if name == "SessionStart":
        _record_session(root, load_config, event)
        return
    if name == "Stop":
        _run_session_end(run, root, load_config, event)
        return
    if target is None:
        return
    relative = _relative_to_root(root, cwd, target.path)
    if relative is None and follow_worktrees:
        # A session started in one checkout often writes into another worktree of the same repository.
        sibling = _sibling_worktree(root, os.path.join(cwd, target.path))
        if sibling is not None:
            root = sibling
            relative = _relative_to_root(root, cwd, target.path)
    if relative is None or not engine.in_scope(relative) or settings.skipped_by_default(relative):
        return
    config = load_config(root)
    if settings.excluded(config, relative):
        return
    run.governance = config.governance
    run.tool = target.tool
    try:
        try:
            current = _current_text(root, relative)
        except UnicodeDecodeError:
            if target.tool != "Write":
                raise
            current = None
        after = hook.proposed_text(target, current)
    except hook.HookInputError as error:
        raise _Refused("--hook", HOOK_INPUT % error)
    except UnicodeDecodeError:
        run.errors.append((relative, None, HOOK_NOT_UTF8))
        return
    except OSError as error:
        run.errors.append((relative, None, error.strerror or str(error)))
        return
    if after is not None:
        run.judge(relative, after, hook.changed_ranges(current, after))


def _execute(args, cwd, stdin):
    run = _Run(_mode(args))
    try:
        root, listed_by_git = _root(args, cwd, run.mode)
        if run.mode == "hook":
            # A write the hook never judges must not depend on the settings file.
            _run_hook(run, root, cwd, lambda judged_root: _load_config(args, judged_root, cwd), stdin,
                      follow_worktrees=not args.root)
            return run
        config = _load_config(args, root, cwd)
        run.governance = config.governance
        if run.mode == "all":
            _run_all(run, root, config, listed_by_git)
        elif run.mode == "diff":
            _run_diff(run, root, config, args.diff)
        elif run.mode == "files":
            named = [_named(run, root, cwd, config, path) for path in args.files]
            for relative in dict.fromkeys(path for path in named if path is not None):
                run.judge_file(root, relative)
        elif run.mode == "staged":
            _run_changes(run, root, config, gitio.STAGED_SPAN, _blob_reader(":./"))
        else:
            relative = _named(run, root, cwd, config, args.stdin_path)
            if relative is not None:
                run.judge(relative, _stdin_text(stdin))
    except _Refused as refusal:
        run.errors.append((refusal.where, None, str(refusal)))
    except gitio.GitError as error:
        run.errors.append(("git", None, str(error)))
    except settings.ConfigError as error:
        run.errors.append((args.config or settings.CONFIG_NAME, None, str(error)))
    return run


def _hook_closing(tool):
    """The lines that end a blocked write's message; a Write also learns to re-send only the comment lines."""
    return report.HOOK_CLOSING + ((report.WRITE_RETRY,) if tool == "Write" else ())


def _hook_verdict(run_result, texts, tool, stderr, event=None):
    """Claude Code blocks a write when its hook exits 2 and shows the agent standard error; a clean write is silent."""
    if not report.exit_code(run_result):
        return 0
    if event == "Stop":
        stderr.write(report.hook_text(run_result, texts, HOOK_STOP_HEADER, STOP_CLOSING))
    else:
        stderr.write(report.hook_text(run_result, texts, HOOK_HEADER, _hook_closing(tool)))
    return 2


def _utf8(stream, errors):
    """Switch a real console stream to UTF-8, so output does not depend on the Windows ANSI code page."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors=errors)


def main(argv=None, stdin=None, stdout=None, stderr=None, cwd=None):
    """Run the check and return the exit code: 0 clean, 1 violations, 2 could not scan."""
    if stdout is None:
        _utf8(sys.stdout, "strict")
    if stderr is None:
        _utf8(sys.stderr, "backslashreplace")
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = _parser()
    args = parser.parse_args(argv)
    if args.hook and args.json:
        parser.error("--json does not apply to --hook, whose verdict is its exit code")
    if args.hook:
        try:
            run = _execute(args, cwd or os.getcwd(), stdin or sys.stdin)
            return _hook_verdict(run.report(), run.texts, run.tool, stderr, run.event)
        except Exception as error:
            stderr.write("%s--hook: could not scan: %s: %s\n" % (HOOK_HEADER, type(error).__name__, error))
            return 2
    result = _execute(args, cwd or os.getcwd(), stdin or sys.stdin).report()
    if args.json:
        stdout.write(report.as_json(result))
        stderr.write(report.as_text(result)[1])
    else:
        out, err = report.as_text(result)
        stdout.write(out)
        stderr.write(err)
    return report.exit_code(result)
