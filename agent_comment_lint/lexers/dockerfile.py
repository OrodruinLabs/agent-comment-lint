"""Dockerfile: a line is a comment only when `#` is its first non-blank character; heredoc payload is content."""
import re
from bisect import bisect_right
from itertools import accumulate

from .base import CODE, COMMENT, STRING, Family, LexError, Line
from .hashlike import HASH_ONLY

# Docker reads these only above the first comment, blank line or instruction.
DIRECTIVE = re.compile(r"\s*#\s*(syntax|escape|check)\s*=\s*(.*?)\s*$", re.IGNORECASE)
HEREDOC_INSTRUCTIONS = ("RUN", "COPY", "ADD")
# A whole word: digits, `<<`, a `-` that is never given back to the name (as in BuildKit), then the name, maybe quoted.
HEREDOC_WORD = re.compile(r"\d*<<(?=(-?))\1(['\"]?)((?a:[\w.-]+))\2")


def _words(text):
    """(start, end) of each shell word: quotes protect whitespace, and a backslash outside single quotes escapes."""
    spans = []
    start = quote = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote or not ch.isspace():
            start = i if start is None else start
            if quote and ch == quote:
                quote = None
            elif ch == "\\" and quote != "'":
                i += 1
            elif not quote and ch in "'\"":
                quote = ch
        elif start is not None:
            spans.append((start, i))
            start = None
        i += 1
    if start is not None:
        spans.append((start, len(text)))
    return spans


def _heredoc_openers(parts):
    """(terminator, strips_tabs, line) for every heredoc a word of the joined (line, text) parts opens, in order."""
    text = "".join(part for _, part in parts)
    ends = list(accumulate(len(part) for _, part in parts))
    openers = []
    for start, end in _words(text):
        hit = HEREDOC_WORD.fullmatch(text, start, end)
        if hit:
            openers.append((hit.group(3), hit.group(1) == "-", parts[bisect_right(ends, start)][0]))
    return openers


def _instruction_word(stripped):
    """The upper-cased instruction keyword, looking through a leading ONBUILD."""
    words = stripped.split(None, 2)
    if words[0].upper() == "ONBUILD" and len(words) > 1:
        return words[1].upper()
    return words[0].upper()


def _comment_line(raw):
    body = raw.lstrip()
    lead = raw[:len(raw) - len(body)]
    return Line(([(CODE, lead)] if lead else []) + [(COMMENT, body)], CODE)


def lex(text):
    """Lex a Dockerfile one line at a time, tracking continued instructions and pending heredocs."""
    out = []
    escape = "\\"
    directives = True
    continuing = False
    heredocs_allowed = False
    parts = []
    pending = []
    active = None
    for number, raw in enumerate(text.splitlines(), 1):
        if active is not None:
            word, strips_tabs, _ = active
            # As in BuildKit, only the line break goes, and for `<<-` the leading tabs; then the match is exact.
            closes = (raw.lstrip("\t") if strips_tabs else raw) == word
            out.append(Line([(CODE, raw)], CODE if closes else STRING))
            if closes:
                active = pending.pop(0) if pending else None
            continue
        stripped = raw.strip()
        directive = DIRECTIVE.match(raw) if directives else None
        if directive:
            if directive.group(1).lower() == "escape" and directive.group(2) in ("\\", "`"):
                escape = directive.group(2)
            out.append(Line([(CODE, raw)], STRING))
            continue
        directives = False
        if stripped.startswith("#"):
            out.append(_comment_line(raw))
            continue
        out.append(Line([(CODE, raw)], CODE) if stripped else Line([], CODE))
        if not stripped:
            continue
        if not continuing:
            heredocs_allowed = _instruction_word(stripped) in HEREDOC_INSTRUCTIONS
            parts = []
        continuing = stripped.endswith(escape)
        # BuildKit reads the heredoc words of the whole instruction, its lines joined where the escapes were.
        parts.append((number, raw.rstrip()[:-1] if continuing else raw))
        if not continuing and heredocs_allowed:
            pending = _heredoc_openers(parts)
            active = pending.pop(0) if pending else None
    if active is not None:
        raise LexError(active[2], "unterminated heredoc <<%s: no closing line before end of file" % active[0])
    return out


FAMILY = Family("dockerfile", (".dockerfile",), HASH_ONLY, lex, ("Dockerfile", "Containerfile"))
