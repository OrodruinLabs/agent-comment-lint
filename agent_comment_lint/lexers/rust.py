"""Rust: block comments nest, raw, byte and C strings and characters are content, and an attribute is code."""
from . import clike
from .base import Family

RUST = clike.Syntax(nested_blocks=True, multiline_strings=True, raw_string="rust", text_block=False,
                    char_literal="rust", line_continuation=False)

FAMILY = Family("rust", (".rs",), clike.MARKERS, clike.lexer(RUST))
