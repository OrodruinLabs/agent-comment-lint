"""Codex's apply_patch format, read and applied as codex-rs/apply-patch does, so the hook judges what Codex writes."""
import re
from collections import namedtuple

BEGIN = "*** Begin Patch"
END = "*** End Patch"
ENVIRONMENT = "*** Environment ID:"
ADD = "*** Add File: "
DELETE = "*** Delete File: "
UPDATE = "*** Update File: "
MOVE = "*** Move to: "
END_OF_FILE = "*** End of File"
ANCHOR = "@@ "
EMPTY_ANCHOR = "@@"
HEREDOCS = ("<<EOF", "<<'EOF'", '<<"EOF"')
UNEXPECTED = ("Unexpected line found in update hunk: '%s'. Every line should start with ' ' (context line), '+' "
              "(added line), or '-' (removed line)")
NOT_FIRST = "The first line of the patch must be '%s'" % BEGIN
NOT_LAST = "The last line of the patch must be '%s'" % END
NOT_A_HEADER = ("'%s' is not a valid hunk header. Valid hunk headers: '*** Add File: {path}', '*** Delete File: "
                "{path}', '*** Update File: {path}'")
# Rust's whitespace: str.strip would also drop the separators \x1c to \x1f.
WHITESPACE = ("\t\n\x0b\x0c\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
              "\u2028\u2029\u202f\u205f\u3000")
PUNCTUATION = str.maketrans("\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u2018\u2019\u201a\u201b\u201c\u201d\u201e"
                            "\u201f\u00a0\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000",
                            "-" * 7 + "'" * 4 + '"' * 4 + " " * 13)

CodexFile = namedtuple("CodexFile", ["kind", "path", "move_to", "content", "hunks"])
CodexFile.__doc__ = ("One file of a patch: its kind (add, update or delete), its path, an update's destination, an "
                     "added file's content, and an update's hunks.")
CodexHunk = namedtuple("CodexHunk", ["anchor", "old_lines", "new_lines", "at_end", "context"], defaults=[()])
CodexHunk.__doc__ = ("One `@@` chunk of an update: the line to find first, the lines it replaces and their "
                     "replacement, whether they end the file, and the (old, new) indices of its context lines.")


class PatchError(Exception):
    """Text Codex's own parser refuses."""


def _trim(text):
    return text.strip(WHITESPACE)


def _chomp(line):
    return line[:-1] if line.endswith("\r") else line


def _bounded(lines):
    """Raises unless the lines open with Begin Patch and close with End Patch."""
    if not lines or _trim(lines[0]) != BEGIN:
        raise PatchError(NOT_FIRST)
    if _trim(lines[-1]) != END:
        raise PatchError(NOT_LAST)


def _patch_lines(text):
    """The patch's lines, the way the lenient mode finds them, with or without a bare heredoc around them."""
    trimmed = _trim(text)
    lines = [_chomp(line) for line in trimmed.split("\n")] if trimmed else []
    try:
        # Codex checks both ends before it parses, so a missing end is named before any fault inside.
        _bounded(lines)
        return lines
    except PatchError:
        if len(lines) < 4 or lines[0] not in HEREDOCS or not lines[-1].endswith("EOF"):
            raise
    _bounded(lines[1:-1])
    return lines[1:-1]


class _Chunk:
    def __init__(self, anchor=None):
        self.anchor = anchor
        self.old = []
        self.new = []
        self.at_end = False
        self.context = []

    def empty(self):
        return not self.old and not self.new

    def context_line(self, line):
        self.context.append((len(self.old), len(self.new)))
        self.old.append(line)
        self.new.append(line)


class _File:
    def __init__(self, kind, path):
        self.kind = kind
        self.path = path
        self.move_to = None
        self.content = []
        self.chunks = []


class _Parser:
    """streaming_parser.rs, one line at a time."""

    def __init__(self):
        self.mode = "start"
        self.files = []
        self.environment = False

    def _check_update(self, line):
        last = self.files[-1] if self.files else None
        if last is None or last.kind != "update":
            return
        if not last.chunks:
            raise PatchError("Update file hunk for path '%s' is empty" % last.path)
        if last.chunks[-1].empty():
            raise PatchError("Update hunk does not contain any lines" if line == END else UNEXPECTED % line)

    def _header(self, line):
        """Whether `line` opened a file or ended the patch."""
        if self.mode == "patch" and line.startswith(ENVIRONMENT):
            if self.environment:
                raise PatchError("apply_patch environment_id cannot be specified more than once")
            if not _trim(line[len(ENVIRONMENT):]):
                raise PatchError("apply_patch environment_id cannot be empty")
            self.environment = True
            return True
        if line == END:
            self._check_update(line)
            self.mode = "ended"
            return True
        for marker, kind in ((ADD, "add"), (DELETE, "delete"), (UPDATE, "update")):
            if line.startswith(marker):
                self._check_update(line)
                self.files.append(_File(kind, line[len(marker):]))
                self.mode = kind
                return True
        return False

    def line(self, line):
        trimmed = _trim(line)
        if self.mode == "start":
            if trimmed != BEGIN:
                raise PatchError(NOT_FIRST)
            self.mode = "patch"
        elif self.mode == "ended":
            if trimmed:
                raise PatchError(NOT_LAST)
        elif self.mode == "update":
            self._update(line)
        elif not self._header(trimmed):
            if self.mode != "add" or not line.startswith("+"):
                raise PatchError(NOT_A_HEADER % trimmed)
            self.files[-1].content.append(line[1:] + "\n")

    def _update(self, line):
        # Leading whitespace starts a context line, so only the end of an update's line is trimmed.
        stripped = line.rstrip(WHITESPACE)
        if self._header(stripped):
            return
        current = self.files[-1]
        chunks = current.chunks
        anchored = stripped == EMPTY_ANCHOR or stripped.startswith(ANCHOR)
        if chunks and chunks[-1].at_end:
            if not stripped:
                return
            if not anchored:
                raise PatchError("Expected update hunk to start with a @@ context marker, got: '%s'" % line)
        if not chunks and current.move_to is None and stripped.startswith(MOVE):
            current.move_to = stripped[len(MOVE):]
        elif anchored:
            if chunks and chunks[-1].empty():
                raise PatchError(UNEXPECTED % line)
            chunks.append(_Chunk(stripped[len(ANCHOR):] if stripped != EMPTY_ANCHOR else None))
        elif stripped == END_OF_FILE:
            if chunks and chunks[-1].empty():
                raise PatchError("Update hunk does not contain any lines")
            if chunks:
                chunks[-1].at_end = True
        elif line == "" or line[0] in " +-":
            if not chunks:
                chunks.append(_Chunk())
            chunk = chunks[-1]
            if line[:1] in ("", " "):
                chunk.context_line(line[1:])
            else:
                (chunk.new if line[0] == "+" else chunk.old).append(line[1:])
        elif chunks and not chunks[-1].empty():
            raise PatchError("Expected update hunk to start with a @@ context marker, got: '%s'" % line)
        else:
            raise PatchError(UNEXPECTED % line)

    def finish(self, line):
        if _trim(line) == END:
            self._check_update(_trim(line))
            self.mode = "ended"
        else:
            self.line(line)
        if self.mode != "ended":
            raise PatchError(NOT_LAST)

    def parsed(self):
        return [CodexFile(found.kind, found.path, found.move_to,
                          "".join(found.content) if found.kind == "add" else None,
                          [CodexHunk(chunk.anchor, chunk.old, chunk.new, chunk.at_end, tuple(chunk.context))
                           for chunk in found.chunks] if found.kind == "update" else None)
                for found in self.files]


def parse_patch(text):
    """The files a patch adds, updates and deletes, in order; PatchError for text Codex refuses."""
    lines = _patch_lines(text)
    parser = _Parser()
    for line in lines[:-1]:
        # Codex's streaming parser strips one more carriage return from every line but the last.
        parser.line(_chomp(line))
    parser.finish(lines[-1])
    return parser.parsed()


def _seek(lines, pattern, start, at_end, preserve=True):
    """seek_sequence.rs: where `pattern` first matches at or after `start`, each pass looser than the last."""
    if not pattern:
        return start
    if len(pattern) > len(lines):
        return None
    first = start
    if at_end:
        # Releases before 0.162.0 seek an end-of-file hunk from the end even when that is before `start`.
        first = max(len(lines) - len(pattern), start) if preserve else len(lines) - len(pattern)
    for key in (str, lambda line: line.rstrip(WHITESPACE), _trim, lambda line: _trim(line).translate(PUNCTUATION)):
        for index in range(first, len(lines) - len(pattern) + 1):
            if all(key(line) == key(want) for line, want in zip(lines[index:index + len(pattern)], pattern)):
                return index
    return None


def _replacements(lines, hunks, preserve):
    """file_update.rs: the (start, length, new lines) each hunk makes, in file order; None where one cannot apply."""
    found = []
    index = 0
    for hunk in hunks:
        if hunk.anchor is not None:
            at = _seek(lines, [hunk.anchor], index, False)
            if at is None:
                return None
            index = at + 1
        if not hunk.old_lines:
            # Releases before 0.162.0 put a pure addition before a final empty line.
            last_empty = not preserve and lines and lines[-1] == ""
            found.append((len(lines) - 1 if last_empty else len(lines), 0, list(hunk.new_lines)))
            continue
        pattern, new = list(hunk.old_lines), list(hunk.new_lines)
        start = _seek(lines, pattern, index, hunk.at_end, preserve)
        if start is None and pattern[-1] == "":
            # A trailing empty line stands for the file's last newline, which the file's lines do not hold.
            pattern = pattern[:-1]
            new = new[:-1] if new and new[-1] == "" else new
            start = _seek(lines, pattern, index, hunk.at_end, preserve)
        if start is None:
            return None
        old_from = new_from = 0
        # Releases before 0.162.0 write a context line as the patch spells it, not as the file holds it.
        for old_at, new_at in hunk.context if preserve else ():
            if old_at >= len(pattern) or new_at >= len(new):
                break
            if (old_from, new_from) != (old_at, new_at):
                found.append((start + old_from, old_at - old_from, new[new_from:new_at]))
            old_from, new_from = old_at + 1, new_at + 1
        if (old_from, new_from) != (len(pattern), len(new)):
            found.append((start + old_from, len(pattern) - old_from, new[new_from:]))
        index = start + len(pattern)
    return sorted(found, key=lambda replacement: replacement[0])


def apply_hunks(text, hunks):
    """The text a Codex update leaves; None where Codex refuses it, or where its releases would write other lines."""
    written = applied(text, hunks)
    if written is None:
        return None
    # The hook cannot tell which release runs it, and releases before 0.162.0 are still installed.
    older = applied(text, hunks, preserve_line_endings=False)
    return written if older is None or older.splitlines() == written.splitlines() else None


def applied(text, hunks, preserve_line_endings=True):
    """The text one Codex release writes: 0.162.0 and later preserve line endings, earlier ones normalize to LF."""
    if not preserve_line_endings:
        return _normalized_to_lf(text, hunks)
    parts = re.split("(\r\n|\r|\n)", text)
    source = list(zip(parts[0::2], parts[1::2])) + ([(parts[-1], None)] if parts[-1] else [])
    replacements = _replacements([line for line, _ending in source], hunks, preserve=True)
    if replacements is None:
        return None
    preferred = next((ending for _line, ending in source if ending), "\n")
    result, done = [], 0
    for start, length, new in replacements:
        result.extend(source[done:start])
        result.extend((line, preferred) for line in new)
        done = start + length
    result.extend(source[done:])
    return "".join(line + (ending or preferred) for line, ending in result)


def _normalized_to_lf(text, hunks):
    """Before 0.162.0, by default: the file split on \\n alone, and each hunk written whole and in reverse order."""
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    replacements = _replacements(lines, hunks, preserve=False)
    if replacements is None:
        return None
    for start, length, new in reversed(replacements):
        lines[start:start + length] = new
    if not lines or lines[-1] != "":
        lines.append("")
    return "\n".join(lines)
