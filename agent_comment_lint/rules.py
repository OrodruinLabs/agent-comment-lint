"""The four checked clauses, as pure functions over lexed lines. Every over-budget block is reported."""
import re
from collections import namedtuple

from .governance import DEFAULT
from .lexers.base import BLOCK_CLOSE, BLOCK_OPEN, COMMENT, STRING, block_prose

MAX_PROSE = 1
MAX_LINE = 120
MAX_ASSERTION_LINES = 2

Finding = namedtuple("Finding", ["rule", "line", "end_line", "message"])
Finding.__doc__ = "One violation: the clause, the inclusive line span it covers, and what was found."

RULE_ORDER = ("C1", "C3", "C5", "C7")

COMPLETE_TAG = re.compile(r"^(?:<(\w{1,64})[^>]{0,200}>.{0,4000}</\1>|<\w{1,64}[^>]{0,200}/>|@\w{1,64}.{0,4000})$")
# A letter or digit in any script: a comment line without one is decoration, such as a ruler, and not prose.
HAS_TEXT = re.compile(r"[^\W_]")
CONCATENATION = re.compile(r'^\s*\+\s*"')
ASSERTION_CONTEXT = re.compile(r"because\s*:|\.Should\(\)|Assert\.")


def _comment_body(stripped, markers):
    """(body, opens) for a stripped line read with no block open; body is None when it is not a comment line."""
    if markers.hash and stripped.startswith("#"):
        return stripped[1:].strip(), False
    if markers.slash and stripped.startswith("///"):
        return stripped[3:].strip(), False
    if markers.slash and stripped.startswith("//"):
        return stripped[2:].strip(), False
    if not markers.block:
        return None, False
    opener = stripped[1:] if stripped.startswith("{") else stripped
    if opener.startswith(BLOCK_OPEN):
        rest = opener[len(BLOCK_OPEN):]
        if BLOCK_CLOSE in rest:
            return None, False
        return block_prose(rest), True
    if markers.star and stripped.startswith("*") and not stripped.startswith(BLOCK_CLOSE):
        return stripped[1:].strip(), False
    return None, False


def _after_close(lineno, stripped, markers):
    """Yield what follows the first `*/` as a block start (`markers` needs star=False); return if it opens one."""
    rest = stripped[stripped.find(BLOCK_CLOSE) + len(BLOCK_CLOSE):].strip()
    if not rest:
        return False
    body, opens = _comment_body(rest, markers)
    yield lineno, body, True, False
    return opens


def comment_lines(raw_lines, lexed, markers):
    """(lineno, body, starts, closing) per comment part: a part that `starts` ends the block before it."""
    # The lexer alone says whether a line starts in a `/* */` block; this says only whether that block opened its line.
    opened_its_line = False
    # No block is open after a close, so a `*` that starts what follows it is code, not a continuation.
    after_close = markers._replace(star=False)
    for lineno, (raw, line) in enumerate(zip(raw_lines, lexed), 1):
        stripped = raw.strip()
        if line.blocks:
            for part in line.blocks:
                yield lineno, part.body, part.opens, part.closes
            # A docstring the lexer placed as a block ends with no `*/` to read past.
            closed = line.opens_in == COMMENT and line.blocks[-1].closes
            opened_its_line = (yield from _after_close(lineno, stripped, after_close)) if closed else False
        elif line.opens_in == STRING:
            opened_its_line = False
            yield lineno, None, False, False
        elif line.opens_in == COMMENT and opened_its_line:
            close = stripped.find(BLOCK_CLOSE)
            yield lineno, block_prose(stripped if close < 0 else stripped[:close]), False, close >= 0
            opened_its_line = close < 0 or (yield from _after_close(lineno, stripped, after_close))
        else:
            body, opened_its_line = _comment_body(stripped, markers)
            yield lineno, body, opened_its_line, False
            if line.opens_in == COMMENT and BLOCK_CLOSE in stripped:
                # A block that opened after code ends here; what follows is not part of it.
                opened_its_line = yield from _after_close(lineno, stripped, after_close)


def prose_runs(raw_lines, lexed, markers):
    """(start, end, count) for every block that holds prose; complete one-line tags and decoration never count."""
    runs = []
    count = start = end = 0

    def close():
        if count:
            runs.append((start, end, count))
        return 0

    for lineno, body, starts, closing in comment_lines(raw_lines, lexed, markers):
        if starts:
            count = close()
        if body is None:
            count = close()
            continue
        if body and HAS_TEXT.search(body) and not COMPLETE_TAG.match(body):
            if count == 0:
                start = lineno
            count += 1
            end = lineno
        if closing:
            count = close()
    close()
    return runs


def check_c1(raw_lines, lexed, markers):
    """One finding per comment block that wraps prose past the budget."""
    return [Finding("C1", start, end, "%d-line prose block (limit %d)" % (count, MAX_PROSE))
            for start, end, count in prose_runs(raw_lines, lexed, markers) if count > MAX_PROSE]


def check_c3(lexed, governance=DEFAULT):
    """One finding per comment that carries a reference from the repository's governance list."""
    out = []
    for lineno, line in enumerate(lexed, 1):
        for kind, text in line.segments or ():
            reference = governance.first_reference(text) if kind == COMMENT else None
            if reference:
                out.append(Finding("C3", lineno, lineno, "governance reference %r" % reference))
    return out


def check_c5(raw_lines):
    """One finding per assertion message concatenated across more lines than the budget."""
    out = []
    run = start = 0
    for index, raw in enumerate(list(raw_lines) + [""]):
        if CONCATENATION.match(raw):
            if run == 0:
                start = index
            run += 1
            continue
        if run:
            out.extend(_assertion_verdict(raw_lines, start, run))
            run = 0
    return out


def _assertion_verdict(raw_lines, start, run):
    total = run + 1
    if total <= MAX_ASSERTION_LINES:
        return []
    window = "\n".join(raw_lines[max(0, start - 3):start + 1])
    if not ASSERTION_CONTEXT.search(window):
        return []
    # `start` indexes the first continuation from zero, so it is also the 1-based line the message opens on.
    return [Finding("C5", start, start + total - 1,
                    "%d-line assertion message (limit %d)" % (total, MAX_ASSERTION_LINES))]


def check_c7(raw_lines, lexed):
    """One finding per over-long line that carries a comment, measured by its full raw length."""
    out = []
    for lineno, (raw, line) in enumerate(zip(raw_lines, lexed), 1):
        if len(raw) > MAX_LINE and any(kind == COMMENT for kind, _ in line.segments or ()):
            out.append(Finding("C7", lineno, lineno, "comment line is %d chars (limit %d)" % (len(raw), MAX_LINE)))
    return out


def unresolved_lines(lexed):
    """How many lines hold a string the line lexers could not close, and so were left unjudged."""
    return sum(1 for line in lexed if line.segments is None)


def check(raw_lines, lexed, markers, governance=DEFAULT):
    """Every finding for one file, ordered by line and then by clause."""
    found = (check_c1(raw_lines, lexed, markers) + check_c3(lexed, governance)
             + check_c5(raw_lines) + check_c7(raw_lines, lexed))
    return sorted(found, key=lambda finding: (finding.line, RULE_ORDER.index(finding.rule), finding.message))
