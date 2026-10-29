"""The language families the policy covers, and the one lookup from a path to its lexer."""
from . import csharp, css, dockerfile, hashlike, javascript, python, ruby, toml
from .base import Family, LexError, Line, Markers

FAMILIES = (csharp.FAMILY, javascript.SCRIPT, javascript.JSX, css.FAMILY,
            hashlike.SHELL, hashlike.YAML, hashlike.HCL, python.FAMILY, ruby.FAMILY,
            toml.FAMILY, dockerfile.FAMILY)

EXTENSIONS = tuple(extension for family in FAMILIES for extension in family.extensions)
NAMES = tuple(name for family in FAMILIES for name in family.names)


def family_for(path):
    """The family that lexes this path, by exact file name and then by extension; None when out of scope."""
    basename = path.replace("\\", "/").rsplit("/", 1)[-1]
    for family in FAMILIES:
        if basename in family.names:
            return family
    for family in FAMILIES:
        if path.endswith(family.extensions):
            return family
    return None


__all__ = ["EXTENSIONS", "FAMILIES", "Family", "LexError", "Line", "Markers", "NAMES", "family_for"]
