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

# With a split index, every write of the temporary index would leave a shared index in the git directory.
SCRATCH_INDEX_SETTINGS = ("core.splitIndex=false",)

# One shape for every diff, whatever the user's or the build agent's git configuration says.
DIFF_SHAPE = ("--inter-hunk-context=0", "--no-color", "--no-ext-diff", "--no-textconv", "--src-prefix=a/",
              "--dst-prefix=b/", "--find-renames", "--relative", "--diff-filter=d")


class GitError(Exception):
    """Git could not answer, so the run has nothing honest to report; `returncode` is git's exit code, if it ran."""

    returncode = None


def _git_bytes(root, *args, env=None, input=None, settings=()):
    command = ["git"]
    for setting in PINNED_SETTINGS + settings:
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


Change = namedtuple("Change", ["added", "same_content", "blob"])
Change.__doc__ = ("One changed file: lines added (None for a file git calls binary), whether its blob is unchanged, "
                  "and the id of its new blob.")


UNREADABLE = "git diff %s printed a record that cannot be read, so the changed %s unknown"
RECORD_KINDS = {True: ("--raw", "files are"), False: ("--numstat", "lines are")}


def _changed_files(text):
    """{path: Change} from `--raw --numstat -z` output; a rename record carries its two names in the next two fields."""
    fields = iter(text.split("\0"))
    blobs = {}
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
                blobs[path] = new_blob
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
    if not set(added) <= set(blobs):
        raise GitError(UNREADABLE % RECORD_KINDS[True])
    return {path: Change(count, path in same_content, blobs[path]) for path, count in added.items()}


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
    """A tree of the whole repository with `paths` (relative to `root`) as on disk, less any other unmerged path."""
    try:
        handle, scratch = tempfile.mkstemp(prefix="agent-comment-lint-index-")
        os.close(handle)
    except OSError as error:
        raise GitError("the temporary index could not be made: %s" % (error.strerror or error))
    try:
        real = git_path(root, "index")
        try:
            if os.path.exists(real):
                shutil.copyfile(real, scratch)
            else:
                # Git refuses an existing empty file as an index.
                os.remove(scratch)
        except OSError as error:
            raise GitError("the temporary index could not be made: %s" % (error.strerror or error))

        def scratch_git(*args, input=None):
            env = {"GIT_INDEX_FILE": scratch}
            return _git_bytes(root, *args, env=env, input=input, settings=SCRATCH_INDEX_SETTINGS)

        listing = "".join(path + "\0" for path in paths).encode("utf-8")
        scratch_git("update-index", "--add", "--remove", "-z", "--stdin", input=listing)
        # Write-tree refuses a conflict mid-merge; a path still unmerged here is one the policy does not cover.
        unmerged = scratch_git("ls-files", "-u", "-z", "--", ":/").split(b"\0")
        names = dict.fromkeys(record.split(b"\t", 1)[1] for record in unmerged if record)
        if names:
            scratch_git("update-index", "--force-remove", "-z", "--stdin", input=b"".join(n + b"\0" for n in names))
        return scratch_git("write-tree").decode("ascii").strip()
    finally:
        try:
            os.remove(scratch)
        except OSError:
            # A stray file in the temp directory is harmless; raising here would turn a good snapshot into a failure.
            pass


def blob(root, spec):
    """The bytes of the blob `spec` names; GitError when it names none."""
    return _git_bytes(root, "cat-file", "blob", spec)


BATCH_UNREADABLE = "git cat-file --batch printed a record that cannot be read"


def read_blobs(root, ids):
    """{id: bytes} for each blob id, all read by one `git cat-file --batch`; GitError when one names no blob."""
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return {}
    out = _git_bytes(root, "cat-file", "--batch", input="".join(oid + "\n" for oid in wanted).encode("ascii"))
    blobs = {}
    position = 0
    try:
        for oid in wanted:
            end = out.index(b"\n", position)
            header = out[position:end].decode("ascii").split(" ")
            if header == [oid, "missing"]:
                raise GitError("git cat-file --batch found no object %s" % oid)
            name, kind, size = header
            start, stop = end + 1, end + 1 + int(size)
            if (name, kind) != (oid, "blob") or out[stop:stop + 1] != b"\n":
                raise GitError(BATCH_UNREADABLE)
            blobs[oid] = out[start:stop]
            position = stop + 1
    except ValueError:
        raise GitError(BATCH_UNREADABLE)
    return blobs


def has_head(root):
    """True once HEAD names a commit; exit 1 is the only answer that means it does not."""
    try:
        _git(root, "rev-parse", "--verify", "-q", "HEAD")
    except GitError as error:
        if error.returncode == 1:
            return False
        raise
    return True


def has_object(root, oid):
    """True when the repository holds the object `oid`; exit 1 is the only answer that means it does not."""
    try:
        _git(root, "cat-file", "-e", oid)
    except GitError as error:
        if error.returncode == 1:
            return False
        raise
    return True


def committed_blob(root, path):
    """The bytes of `path` at HEAD, or None when HEAD lacks it."""
    if not _git(root, "ls-tree", "-z", "HEAD", "--", path):
        return None
    return blob(root, "HEAD:./" + path)
