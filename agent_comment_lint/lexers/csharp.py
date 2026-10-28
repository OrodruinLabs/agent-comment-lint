"""C#: `//`, `///` and `/* */` comments; raw string literals are content across lines."""
import re

from .base import Family, Markers
from .linescan import delimited_payload, scan_lines

# A `$` or `$$` interpolation prefix needs no match of its own: the quote run alone fixes the closer.
RAW_STRING_OPEN = re.compile(r'(?<!\\)("{3,})')


def raw_string_payload(lines):
    """Per-line flags for the lines inside a multi-line raw string, which are fixture content."""
    return delimited_payload(lines, RAW_STRING_OPEN, hash_marker=False, slash_marker=True,
                             kind="raw string literal")


def lex(text):
    """Lex C# source."""
    lines = text.splitlines()
    return scan_lines(lines, raw_string_payload(lines), [None] * len(lines), hash_marker=False, slash_marker=True)


FAMILY = Family("csharp", (".cs",), Markers(hash=False, slash=True, block=True, star=True), lex)
