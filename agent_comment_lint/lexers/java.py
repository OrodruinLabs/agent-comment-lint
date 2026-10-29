"""Java: text blocks and characters are content, and an annotation is code."""
from . import clike
from .base import Family

JAVA = clike.Syntax(False, False, None, True, "simple", False)

FAMILY = Family("java", (".java",), clike.MARKERS, clike.lexer(JAVA))
