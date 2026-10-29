"""The only module that runs git. Every failure surfaces as GitError, never as an empty result."""
import os
import re
import shutil
import subprocess
import tempfile
from collections import namedtuple

# Refs reach git as one argument with no shell, so `~`, `^` and `@{}` are safe and must still resolve.
REF_PATTERN = re.compile(r"^[A-Za-z0-9._/@{}^~-]+$")

# Paths print unquoted. Git counts added lines differently at another context, and `-U0` on the count adds a patch.
PINNED_SETTINGS = ("core.quotePath=false", "diff.context=0")

# Git lets this variable beat `-U0` and `diff.context` alike when it prints a patch; the count never reads it.
UNPINNABLE_ENVIRONMENT = ("GIT_DIFF_OPTS",)

# One shape for every diff, whatever the user's or the build agent's git configuration says.
DIFF_SHAPE = ("--inter-hunk-context=0", "--no-color", "--no-ext-diff", "--no-textconv", "--src-prefix=a/",
              "--dst-prefix=b/", "--find-renames", "--relative", "--diff-filter=d")


class GitError(Exception):
    """Git could not answer, so the run has nothing honest to report; `returncode` is git's exit code, if it ran."""

    returncode = None


def _git_bytes(root, *args, env=None, input=None):
    command = ["git"]
    for setting in PINNED_SETTINGS:
        command += ["-c", setting]
    environment = {name: value for name, value in os.environ.items() if name not in UNPINNABLE_ENVIRONMENT}
    environment.update(env or {})
    try:
        done = subprocess.run(command + list(args), cwd=root, capture_output=True, env=environment, input=input)
    except OSError as error:
        raise GitError("git could not be run: %s" % (error.strerror or error))
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
        error = GitError("git %s failed: %s" % (args[0], detail[-1] if detail else "exit %d" % done.returncode))
        error.returncode = done.returncode
        raise error
    return done.stdout


def _git(root, *args):
    return _git_bytes(root, *args).decode("utf-8", errors="replace")


def claims_repository(directory):
    """True when a `.git` entry in `directory` or a parent, or the environment, names a repository."""
    if os.environ.get("GIT_DIR"):
        return True
    current = os.path.realpath(directory)
    while True:
        if os.path.lexists(os.path.join(current, ".git")):
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def toplevel(directory):
    """The top directory of the work tree that holds `directory`; GitError when git names none."""
    return _git(directory, "rev-parse", "--show-toplevel").strip()


def common_dir(directory):
    """The git directory every worktree of the repository holding `directory` shares; GitError when git names none."""
    return os.path.realpath(os.path.join(directory, _git(directory, "rev-parse", "--git-common-dir").strip()))


def listed_files(root):
    """Tracked plus untracked-unignored paths under `root`, which must be inside a work tree."""
    out = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return [path for path in out.split("\0") if path]


def diff_span(root, base):
    """The arguments selecting `BASE...HEAD`, once BASE is known to name a commit; git's reason is kept when not."""
    if not base or base.startswith("-") or not REF_PATTERN.match(base):
        raise GitError("--diff: %r is not a valid git ref" % base)
    try:
        _git(root, "rev-parse", "--verify", base + "^{commit}")
    except GitError as error:
        raise GitError("--diff: %r does not resolve to a commit (%s)" % (base, error))
    return (base + "...HEAD",)


STAGED_SPAN = ("--cached",)


Change = namedtuple("Change", ["added", "same_content"])
Change.__doc__ = "One changed file: lines added (None for a file git calls binary), and whether its blob is unchanged."


UNREADABLE = "git diff %s printed a record that cannot be read, so the changed %s unknown"
RECORD_KINDS = {True: ("--raw", "files are"), False: ("--numstat", "lines are")}


def _changed_files(text):
    """{path: Change} from `--raw --numstat -z` output; a rename record carries its two names in the next two fields."""
    fields = iter(text.split("\0"))
    same_content = set()
    added = {}
    for field in fields:
        if not field:
            continue
        raw = field.startswith(":")
        try:
            if raw:
                _old_mode, _new_mode, old_blob, new_blob, status = field.split(" ")
                path = next(fields)
                if status[:1] in ("R", "C"):
                    path = next(fields)
                if old_blob == new_blob:
                    same_content.add(path)
                continue
            count, _deleted, path = field.split("\t", 2)
            if not path:
                next(fields)
                path = next(fields)
            added[path] = None if count == "-" else int(count)
        except (ValueError, StopIteration):
            raise GitError(UNREADABLE % RECORD_KINDS[raw])
    return {path: Change(count, path in same_content) for path, count in added.items()}


def changed_files(root, span):
    """{path: Change} for each path the span adds or changes under `root`."""
    return _changed_files(_git(root, "diff", "--raw", "--numstat", "-z", "--no-abbrev", *DIFF_SHAPE, *span))


def changed_diff(root, span):
    """The zero-context diff of the same span, for `diff.parse_diff_ranges`."""
    return _git(root, "diff", *DIFF_SHAPE, *span)


def git_path(root, name):
    """The absolute form of `git rev-parse --git-path NAME`, which git prints relative to `root`."""
    return os.path.abspath(os.path.join(root, _git(root, "rev-parse", "--git-path", name).strip()))


def snapshot_tree(root, paths):
    """The id of a tree holding `paths` as on disk, built in a copy of the index so the real one is untouched."""
    handle, scratch = tempfile.mkstemp(prefix="agent-comment-lint-index-")
    os.close(handle)
    try:
        real = git_path(root, "index")
        if os.path.exists(real):
            shutil.copyfile(real, scratch)
        else:
            # Git refuses an existing empty file as an index.
            os.remove(scratch)
        env = {"GIT_INDEX_FILE": scratch}
        listing = "".join(path + "\0" for path in paths).encode("utf-8")
        _git_bytes(root, "update-index", "--add", "--remove", "-z", "--stdin", env=env, input=listing)
        return _git_bytes(root, "write-tree", env=env).decode("ascii").strip()
    finally:
        if os.path.exists(scratch):
            os.remove(scratch)


def blob(root, spec):
    """The bytes of the blob `spec` names; GitError when it names none."""
    return _git_bytes(root, "cat-file", "blob", spec)


def has_head(root):
    """True once HEAD names a commit; exit 1 is the only answer that means it does not."""
    try:
        _git(root, "rev-parse", "--verify", "-q", "HEAD")
    except GitError as error:
        if error.returncode == 1:
            return False
        raise
    return True


def committed_blob(root, path):
    """The bytes of `path` at HEAD, or None when HEAD lacks it."""
    if not _git(root, "ls-tree", "-z", "HEAD", "--", path):
        return None
    return blob(root, "HEAD:" + path)
