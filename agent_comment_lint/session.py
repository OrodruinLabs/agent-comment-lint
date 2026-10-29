"""Per-session snapshot files: a tree id recorded when a session starts, read back when it stops."""
import os
import re
import time

SESSIONS = "agent-comment-lint/sessions"
# `\Z`, unlike `$`, does not match before a final newline, so each id must be the whole string.
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}\Z")
OBJECT_ID = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?\Z")
MAX_AGE_SECONDS = 7 * 24 * 3600


def _prune(directory):
    cutoff = time.time() - MAX_AGE_SECONDS
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            # A file another session removed first, or one that cannot be removed, is not worth failing a start.
            pass


def record(directory, session_id, tree):
    """Write `tree` as the session's snapshot unless one is already recorded; drop snapshots older than a week."""
    os.makedirs(directory, exist_ok=True)
    _prune(directory)
    try:
        with open(os.path.join(directory, session_id), "x", encoding="ascii") as handle:
            handle.write(tree.strip())
    except FileExistsError:
        pass


def recorded(directory, session_id):
    """The tree id recorded for the session; None when there is none or the file holds anything else."""
    try:
        with open(os.path.join(directory, session_id), encoding="ascii") as handle:
            text = handle.read().strip()
    except (OSError, UnicodeDecodeError):
        return None
    # The text reaches git as an argument, so only a full object id counts as a snapshot.
    return text if OBJECT_ID.match(text) else None
