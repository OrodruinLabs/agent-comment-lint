"""TOML: `#` comments; basic, literal and multi-line strings are content."""
from .base import CODE, COMMENT, STRING, Family, LexError, Line
from .hashlike import HASH_ONLY

# TOML allows up to two quotes beside the three that close a multi-line string.
MAX_CLOSING_RUN = 5


def _run_length(line, i):
    end = i
    while end < len(line) and line[end] == line[i]:
        end += 1
    return end - i


def _multi_line_end(line, i, quote):
    """Index just past the closing triple quote of a multi-line string read from i; None when not on this line."""
    while i < len(line):
        if quote == '"' and line[i] == "\\":
            i += 2
        elif line[i] == quote:
            run = _run_length(line, i)
            if run >= 3:
                return i + min(run, MAX_CLOSING_RUN)
            i += run
        else:
            i += 1
    return None


def _single_line_end(line, i, quote):
    """Index just past the one-line string whose body starts at i; None when it does not close on this line."""
    while i < len(line):
        if quote == '"' and line[i] == "\\":
            i += 2
        elif line[i] == quote:
            return i + 1
        else:
            i += 1
    return None


def _scan(line, quote):
    """(segments, still_open_quote) for a line that starts in a multi-line string of `quote`, or in code if None."""
    segments = []
    i = start = 0

    def flush(kind, upto):
        if upto > start:
            segments.append((kind, line[start:upto]))

    if quote is not None:
        end = _multi_line_end(line, 0, quote)
        if end is None:
            return [(STRING, line)], quote
        segments.append((STRING, line[:end]))
        i = start = end
    while i < len(line):
        ch = line[i]
        if ch == "#":
            flush(CODE, i)
            segments.append((COMMENT, line[i:]))
            return segments, None
        if ch in "\"'":
            flush(CODE, i)
            if line.startswith(ch * 3, i):
                end = _multi_line_end(line, i + 3, ch)
            else:
                end = _single_line_end(line, i + 1, ch)
            if end is None:
                if line.startswith(ch * 3, i):
                    segments.append((STRING, line[i:]))
                    return segments, ch
                return None, None
            segments.append((STRING, line[i:end]))
            i = start = end
        else:
            i += 1
    flush(CODE, len(line))
    return segments, None


def lex(text):
    """Lex TOML source one line at a time, carrying an open multi-line string across lines."""
    out = []
    quote = None
    opened_at = 0
    for number, raw in enumerate(text.splitlines(), 1):
        was_open = quote is not None
        segments, quote = _scan(raw, quote)
        if quote is not None and not was_open:
            opened_at = number
        out.append(Line(segments, STRING if was_open else CODE))
    if quote is not None:
        raise LexError(opened_at, "unterminated multi-line string: no closing %s before end of file" % (quote * 3))
    return out


FAMILY = Family("toml", (".toml",), HASH_ONLY, lex)
