"""Dockerfile: a line is a comment only when `#` is its first non-blank character; heredoc payload is content."""
import re

from .base import CODE, COMMENT, STRING, Family, LexError, Line
from .hashlike import HASH_ONLY, HEREDOC_START, _is_shift
from .linescan import live_code_hit

# Docker reads these only above the first comment, blank line or instruction.
DIRECTIVE = re.compile(r"\s*#\s*(syntax|escape|check)\s*=\s*(.*?)\s*$", re.IGNORECASE)
HEREDOC_INSTRUCTIONS = ("RUN", "COPY", "ADD")


def _heredoc_openers(raw):
    """(terminator, strips_tabs) for every heredoc opened on this line, in order."""
    openers = []
    masked = raw
    while True:
        hit = live_code_hit(masked, HEREDOC_START, hash_marker=True, slash_marker=False)
        if hit is None:
            return openers
        if not _is_shift(masked, hit):
            openers.append((hit.group(2), hit.group().startswith("<<-")))
        masked = " " * hit.end() + masked[hit.end():]


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
    pending = []
    active = None
    for number, raw in enumerate(text.splitlines(), 1):
        if active is not None:
            word, strips_tabs, _ = active
            closes = (raw.lstrip("\t") if strips_tabs else raw).strip() == word
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
        if heredocs_allowed:
            pending.extend((word, strips_tabs, number) for word, strips_tabs in _heredoc_openers(raw))
        continuing = stripped.endswith(escape)
        if not continuing and pending:
            active = pending.pop(0)
    if active is not None:
        raise LexError(active[2], "unterminated heredoc <<%s: no closing line before end of file" % active[0])
    return out


FAMILY = Family("dockerfile", (".dockerfile",), HASH_ONLY, lex, ("Dockerfile", "Containerfile"))
