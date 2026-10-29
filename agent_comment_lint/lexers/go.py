"""Go: backtick raw strings and runes are content, and a directive such as `//go:build` is not comment prose."""
import re

from . import clike
from .base import CODE, COMMENT, STRING, Family, Line

GO = clike.Syntax(nested_blocks=False, multiline_strings=False, raw_string="backtick", text_block=False,
                  char_literal="simple", line_continuation=False)
# What go/ast's isDirective accepts, a bare `//nolint`, and the `// +build` line that came before `//go:build`.
DIRECTIVE = re.compile(r"//(?:line |extern |export |[a-z0-9]+:[a-z0-9]|nolint(?:[ \t]|$))|//[ \t]*\+build(?:[ \t]|$)")
# In a directive, a quoted argument is skipped whole; a quote that never closes leaves no reason to find.
DIRECTIVE_PART = re.compile(r'"(?:\\.|[^"\\])*"|`[^`]*`|(?P<unclosed>["`])|[ \t](?P<reason>//)')

_lex = clike.lexer(GO)


def _is_directive(line):
    """True for a line that holds a directive comment and nothing else but space."""
    if line.opens_in != CODE or line.blocks or not line.segments:
        return False
    kind, text = line.segments[-1]
    lead = "".join(part for _, part in line.segments[:-1])
    return kind == COMMENT and not lead.strip() and DIRECTIVE.match(text) is not None


def _reason_start(raw):
    """Index of the `//` that starts a directive's reason: after a space or tab, outside quotes; None when none."""
    for part in DIRECTIVE_PART.finditer(raw, len(raw) - len(raw.lstrip()) + 2):
        if part.group("unclosed"):
            return None
        if part.group("reason"):
            return part.start("reason")
    return None


def _directive_line(line):
    """The directive as content that opens in a string; from its reason on, it is a trailing comment."""
    raw = "".join(part for _, part in line.segments)
    reason = _reason_start(raw)
    if reason is None:
        return Line([(CODE, raw)], STRING)
    return Line([(CODE, raw[:reason]), (COMMENT, raw[reason:])], STRING)


def lex(text):
    """Lex Go; a directive line opens in a string, as a Dockerfile parser directive does, so C1 never counts it."""
    return [_directive_line(line) if _is_directive(line) else line for line in _lex(text)]


FAMILY = Family("go", (".go",), clike.MARKERS, lex)
