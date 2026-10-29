"""Java: text blocks and characters are content, and an annotation is code."""
from . import clike
from .base import Family

JAVA = clike.Syntax(nested_blocks=False, multiline_strings=False, raw_string=None, text_block=True,
                    char_literal="simple", line_continuation=False)

FAMILY = Family("java", (".java",), clike.MARKERS, clike.lexer(JAVA))
