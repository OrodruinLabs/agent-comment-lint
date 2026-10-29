"""Per-session snapshot files: a tree id recorded when a session starts, read back when it stops."""
import os
import re
import time

SESSIONS = "agent-comment-lint/sessions"
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
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
            handle.write(tree)
    except FileExistsError:
        pass


def recorded(directory, session_id):
    """The tree recorded for the session; None when there is none."""
    try:
        with open(os.path.join(directory, session_id), encoding="ascii") as handle:
            return handle.read().strip() or None
    except (OSError, UnicodeDecodeError):
        return None
