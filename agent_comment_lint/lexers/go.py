"""Go: backtick raw strings and runes are content, and a directive such as `//go:build` is not comment prose."""
import re

from . import clike
from .base import CODE, COMMENT, STRING, Family, Line

GO = clike.Syntax(False, False, "backtick", False, "simple", False)
# What go/ast's isDirective accepts, and the `// +build` line that came before `//go:build`.
DIRECTIVE = re.compile(r"//(?:line |extern |export |[a-z0-9]+:[a-z0-9])|//[ \t]*\+build(?:[ \t]|$)")

_lex = clike.lexer(GO)


def _is_directive(line):
    """True for a line that holds a directive comment and nothing else but space."""
    if line.opens_in != CODE or line.blocks or not line.segments:
        return False
    kind, text = line.segments[-1]
    lead = "".join(part for _, part in line.segments[:-1])
    return kind == COMMENT and not lead.strip() and DIRECTIVE.match(text) is not None


def lex(text):
    """Lex Go; a directive line is content that opens in a string, as a Dockerfile parser directive is."""
    return [Line([(CODE, "".join(part for _, part in line.segments))], STRING) if _is_directive(line) else line
            for line in _lex(text)]


FAMILY = Family("go", (".go",), clike.MARKERS, lex)
