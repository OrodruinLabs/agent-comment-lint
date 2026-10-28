"""The language families the policy covers, and the one lookup from a path to its lexer."""
from . import csharp, css, hashlike, javascript, python
from .base import Family, LexError, Line, Markers

FAMILIES = (csharp.FAMILY, javascript.SCRIPT, javascript.JSX, css.FAMILY,
            hashlike.SHELL, hashlike.YAML, hashlike.HCL, python.FAMILY)

EXTENSIONS = tuple(extension for family in FAMILIES for extension in family.extensions)


def family_for(path):
    """The family that lexes this path, by extension; None when the path is out of scope."""
    for family in FAMILIES:
        if path.endswith(family.extensions):
            return family
    return None


__all__ = ["EXTENSIONS", "FAMILIES", "Family", "LexError", "Line", "Markers", "family_for"]
