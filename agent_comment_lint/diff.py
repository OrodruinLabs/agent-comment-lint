"""Parsing a unified diff into the new-file line ranges it adds or changes. No git needed."""
import re
from collections import namedtuple

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

# Git quotes a name that holds a quote, a backslash or a control character, whatever `core.quotePath` says.
QUOTED_ESCAPE = re.compile(r"\\([0-7]{1,3}|.)")
ESCAPED_BYTES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13}


class Hunk(namedtuple("Hunk", ["old_count", "start", "new_count"])):
    """One `@@ -a,b +c,d @@` header: the old line count, the first new line and the new line count."""

    def new_range(self):
        """Inclusive (start, end) of the new-file lines the hunk covers; None for a pure deletion."""
        return (self.start, self.start + self.new_count - 1) if self.new_count else None


def parse_hunk(header):
    """The Hunk a `@@ -a,b +c,d @@` header announces; None for any other line."""
    match = HUNK_HEADER.match(header)
    if not match:
        return None
    old_count, start, new_count = match.groups()
    return Hunk(1 if old_count is None else int(old_count), int(start), 1 if new_count is None else int(new_count))


def _escaped_byte(match):
    code = match.group(1)
    if code[0] in "01234567":
        return chr(int(code, 8) & 0xFF)
    return chr(ESCAPED_BYTES.get(code, ord(code)))


def _unquoted(name):
    """A name as git C-quotes it, back to its text: escapes become their bytes, and the bytes are read as UTF-8."""
    if len(name) < 2 or not (name.startswith('"') and name.endswith('"')):
        return name
    escaped = name[1:-1].encode("utf-8").decode("latin-1")
    return QUOTED_ESCAPE.sub(_escaped_byte, escaped).encode("latin-1").decode("utf-8", errors="replace")


def _new_path(plus_line):
    """The path a `+++ ...` line names; None for `/dev/null`, which marks a deleted file."""
    target = _unquoted(plus_line[4:].split("\t", 1)[0])
    if target == "/dev/null":
        return None
    return target[2:] if target[:2] in ("a/", "b/") else target


class _HunkBody:
    """Counts down the lines a hunk header announced, so a source line shaped like a header is never read as one."""

    def __init__(self):
        self.old = self.new = 0

    def open(self, hunk):
        self.old, self.new = hunk.old_count, hunk.new_count

    def consume(self, line):
        """Take `line` off the announced counts; False, with the body closed, when it is not one of those lines."""
        marker = line[:1]
        if marker == "\\":
            return True
        if marker == "-" and self.old:
            self.old -= 1
        elif marker == "+" and self.new:
            self.new -= 1
        elif marker == " " and self.old and self.new:
            self.old -= 1
            self.new -= 1
        else:
            self.old = self.new = 0
            return False
        return True


def parse_diff_ranges(diff_text):
    """Map each file in a `git diff -U0` to its new-file (start, end) ranges; empty when it only loses lines."""
    ranges = {}
    current = None
    body = _HunkBody()
    for line in diff_text.split("\n"):
        if body.consume(line):
            continue
        if line.startswith("+++ "):
            current = _new_path(line)
            if current is not None:
                ranges.setdefault(current, [])
            continue
        hunk = parse_hunk(line) if current is not None else None
        if hunk is not None:
            body.open(hunk)
            added = hunk.new_range()
            if added:
                ranges[current].append(added)
    return ranges
