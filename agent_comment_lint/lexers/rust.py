"""Rust: block comments nest, raw, byte and C strings and characters are content, and an attribute is code."""
from . import clike
from .base import Family

RUST = clike.Syntax(True, True, "rust", False, "rust", False)

FAMILY = Family("rust", (".rs",), clike.MARKERS, clike.lexer(RUST))
