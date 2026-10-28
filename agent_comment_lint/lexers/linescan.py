"""Line-at-a-time scanning shared by the families whose strings are resolved one line at a time."""
import re

from .base import BLOCK_CLOSE, BLOCK_OPEN, CODE, COMMENT, STRING, LexError, Line

CHAR_LITERAL = re.compile(r"'(?:\\.|[^'\\])'")
STRING_OPEN = re.compile(r'@\$"|\$@"|@"|\$"|"')
NON_SOURCE_KINDS = (STRING, COMMENT)


def _skip_interpolation_hole(line, i):
    """Index just past a `{...}` interpolation hole entered at i; None when it holds a quote or never closes."""
    depth = 1
    while i < len(line) and depth:
        if line[i] == "{":
            depth += 1
        elif line[i] == "}":
            depth -= 1
        elif line[i] == '"':
            return None
        i += 1
    return None if depth else i


def _is_doubled(line, i, chars):
    return line[i] in chars and i + 1 < len(line) and line[i + 1] == line[i]


def string_end(line, i, *, verbatim, interpolated):
    """Index just past the string whose body starts at i; None when it does not close on this line."""
    n = len(line)
    while i < n:
        ch = line[i]
        if interpolated and ch == "{" and not _is_doubled(line, i, "{"):
            i = _skip_interpolation_hole(line, i + 1)
            if i is None:
                return None
        elif interpolated and _is_doubled(line, i, "{}"):
            i += 2
        elif ch == '"':
            if not (verbatim and _is_doubled(line, i, '"')):
                return i + 1
            i += 2
        elif not verbatim and ch == "\\":
            i += 2
        else:
            i += 1
    return None


def _single_quoted_end(line, i):
    """Index just past a single-quoted scalar whose body starts at i; None when it does not close on this line."""
    n = len(line)
    while i < n:
        if line[i] != "'":
            i += 1
        elif i + 1 < n and line[i + 1] == "'":
            i += 2
        else:
            return i + 1
    return None


def scan_line(line, *, hash_marker, slash_marker):
    """Split a line into (kind, text) segments; None when a string on it does not close on the line."""
    n = len(line)
    i = start = 0
    segments = []

    def flush(upto):
        if upto > start:
            segments.append((CODE, line[start:upto]))

    while i < n:
        ch = line[i]
        if hash_marker and ch == "'":
            end = _single_quoted_end(line, i + 1)
            if end is None:
                i += 1
                continue
            flush(i)
            segments.append((STRING, line[i:end]))
            i = start = end
            continue
        literal = CHAR_LITERAL.match(line, i)
        if literal:
            i = literal.end()
            continue
        two = line[i:i + 2]
        if (hash_marker and ch == "#") or (slash_marker and two == "//"):
            flush(i)
            segments.append((COMMENT, line[i:]))
            return segments
        if slash_marker and two == BLOCK_OPEN:
            flush(i)
            close = line.find(BLOCK_CLOSE, i + 2)
            if close == -1:
                segments.append((COMMENT, line[i:]))
                return segments
            segments.append((COMMENT, line[i:close + 2]))
            i = start = close + 2
            continue
        opener = STRING_OPEN.match(line, i)
        if opener:
            flush(i)
            end = string_end(line, opener.end(), verbatim="@" in opener.group(), interpolated="$" in opener.group())
            if end is None:
                return None
            segments.append((STRING, line[i:end]))
            i = start = end
            continue
        i += 1
    flush(n)
    return segments


def _span_is_quoted(segments, start, end):
    """True when [start, end) sits wholly inside one string or comment segment, so it is not live code."""
    offset = 0
    for kind, text in segments:
        seg_end = offset + len(text)
        if kind in NON_SOURCE_KINDS and offset <= start and end <= seg_end:
            return True
        offset = seg_end
    return False


def live_code_hit(raw, pattern, *, hash_marker, slash_marker):
    """The first match of `pattern` no string or comment buries; a line that does not resolve is read whole."""
    hits = list(pattern.finditer(raw))
    if not hits:
        return None
    segments = scan_line(raw, hash_marker=hash_marker, slash_marker=slash_marker)
    for hit in hits:
        if segments is None or not _span_is_quoted(segments, hit.start(), hit.end()):
            return hit
    return None


def closing_line(lines, start, closer):
    """Index of the first line after `start` holding the closing delimiter; None when there is none."""
    for index in range(start + 1, len(lines)):
        if closer in lines[index]:
            return index
    return None


def delimited_payload(lines, opener, *, hash_marker, slash_marker, kind, strict=True):
    """Flags a multi-line string's payload lines; an unclosed `kind` is refused when `strict`, else read as code."""
    payload = [False] * len(lines)
    index = 0
    while index < len(lines):
        hit = live_code_hit(lines[index], opener, hash_marker=hash_marker, slash_marker=slash_marker)
        if hit is None or hit.group(1) in lines[index][hit.end():]:
            index += 1
            continue
        close_at = closing_line(lines, index, hit.group(1))
        if close_at is None:
            if strict:
                raise LexError(index + 1, "unterminated %s: no closing %s before end of file" % (kind, hit.group(1)))
            index += 1
            continue
        for inside in range(index + 1, close_at + 1):
            payload[inside] = True
        index = close_at + 1
    return payload


def _opens_unclosed_block(segments):
    if not segments or segments[-1][0] != COMMENT:
        return False
    last = segments[-1][1]
    return last.startswith(BLOCK_OPEN) and BLOCK_CLOSE not in last


def _continued_block_line(raw, *, hash_marker, slash_marker):
    """(segments, still_in_block) for a line that starts inside a `/* ... */` block."""
    close = raw.find(BLOCK_CLOSE)
    if close == -1:
        return [(COMMENT, raw)], True
    rest = scan_line(raw[close + 2:], hash_marker=hash_marker, slash_marker=slash_marker)
    if rest is None:
        return None, False
    segments = [(COMMENT, raw[:close + 2])] + rest
    return segments, _opens_unclosed_block(segments)


def scan_lines(lines, payload, docs, *, hash_marker, slash_marker):
    """One Line per source line; `payload` flags string content and `docs` carries docstring lines."""
    out = []
    in_block = False
    for index, raw in enumerate(lines):
        if docs[index] is not None:
            out.append(Line([(COMMENT, raw)], CODE, (docs[index],)))
            in_block = False
        elif payload[index]:
            out.append(Line([(CODE, raw)], STRING))
            in_block = False
        elif in_block:
            segments, in_block = _continued_block_line(raw, hash_marker=hash_marker, slash_marker=slash_marker)
            out.append(Line(segments, COMMENT))
        else:
            segments = scan_line(raw, hash_marker=hash_marker, slash_marker=slash_marker)
            in_block = segments is not None and _opens_unclosed_block(segments)
            out.append(Line(segments, CODE))
    return out
