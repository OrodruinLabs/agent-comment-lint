"""The C family: `//` and `/* */` comments, with strings, characters and raw strings read as content."""
import re
from collections import namedtuple

from .base import CODE, COMMENT, STRING, BlockLine, LexError, LineBuilder, Markers, normalized

Syntax = namedtuple("Syntax", ["nested_blocks", "multiline_strings", "raw_string", "text_block", "char_literal",
                               "line_continuation"])
Syntax.__doc__ = "What one C-family language adds to `//`, `/* */`, `\"...\"` and `'...'`, one option per field."

MARKERS = Markers(hash=False, slash=True, block=True, star=False)

WORD = re.compile(r"\w*")
BLOCK_DELIMITER = re.compile(r"/\*|\*/")
TEXT_BLOCK = '"""'
RUST_RAW = re.compile(r'(#*)"')
RUST_RAW_PREFIXES = ("r", "br", "cr")
SWIFT_RAW = re.compile(r'(#+)"')
# The delimiter has at most 16 characters, and none of them is a parenthesis, a backslash or a space.
CPP_RAW = re.compile(r'"([^()\\\s]{0,16})\(')
CPP_RAW_PREFIXES = ("R", "LR", "uR", "UR", "u8R")
CHAR_LITERALS = ("simple", "rust")
RUST_CHAR = re.compile(r"'(?:\\(?:u\{[0-9a-fA-F_]{1,6}\}|x[0-9a-fA-F]{2}|.)|[^\\'\n])'")


def lexer(syntax):
    """The `lex(text) -> [Line]` of the C-family language that `syntax` describes."""
    if syntax.raw_string not in (None,) + tuple(RAW_STRINGS) or syntax.char_literal not in CHAR_LITERALS:
        raise ValueError("raw_string must be None or one of %s, and char_literal one of %s: %r"
                         % (", ".join(RAW_STRINGS), ", ".join(CHAR_LITERALS), syntax))

    def lex(text):
        return _lex(normalized(text), syntax)
    return lex


def _lex(src, syntax):
    """Walk the source once; a comment, string or character that never closes stops the lex at its opening line."""
    if not src:
        return []
    out = LineBuilder()
    i = 0
    while i < len(src):
        if src[i] == "\n":
            out.newline(CODE)
            i += 1
        elif src.startswith("//", i):
            i = _line_comment(out, src, i, syntax.line_continuation)
        elif src.startswith("/*", i):
            end = _nested_block_end(src, i) if syntax.nested_blocks else _close(src, i, i + 2, "*/", "block comment")
            out.emit_block_comment(src[i:end])
            placed = syntax.nested_blocks and "\n" in src[i:end]
            i = _after_nested_close(out, src, end, syntax.line_continuation) if placed else end
        else:
            word = WORD.match(src, i).end()
            end = _literal_end(src, i, word, syntax)
            if end is None:
                end = max(word, i + 1)
                out.emit(CODE, src[i:end])
            else:
                out.emit_span(STRING, src[i:end])
            i = end
    return out.finish()


def _line_comment(out, src, i, continues, place=False):
    """Emit the `//` comment at i; with `continues`, a backslash that ends a line carries it onto the next one."""
    end = _line_end(src, i)
    while continues and end < len(src) and src[i:end].rstrip(" \t").endswith("\\"):
        end = _line_end(src, end + 1)
    comment = src[i:end]
    if "\n" not in comment and not place:
        out.emit(COMMENT, comment)
        return end
    after_code = bool(src[src.rfind("\n", 0, i) + 1:i].strip())
    for index, part in enumerate(comment.split("\n")):
        if index:
            out.newline(COMMENT)
        out.emit(COMMENT, part)
        # A blank line ends the logical line, and placing it would keep the block open into the next comment.
        if index and not part.strip():
            break
        # Behind code the first line starts a block, as a comment after a block close does; the rest join it.
        out.place(BlockLine(_line_prose(part, not index), after_code and not index, False))
    return end


def _line_prose(part, first):
    """The prose of one line of a placed `//` comment, without its slashes or a trailing backslash."""
    text = part.strip()
    if first:
        text = text[3:] if text.startswith("///") else text[2:]
    return text.rstrip("\\ \t").strip()


def _line_end(src, i):
    end = src.find("\n", i)
    return len(src) if end < 0 else end


def _after_nested_close(out, src, i, continues):
    """Place what follows a nested close on its line: C1 reads past the first `*/`, which may close an inner block."""
    j = i
    while src[j:j + 1] in (" ", "\t"):
        j += 1
    if src.startswith("//", j):
        out.emit(CODE, src[i:j])
        return _line_comment(out, src, j, continues, place=True)
    out.place(BlockLine(None, True, False))
    return i


def _nested_block_end(src, i):
    """Index just past the `/* */` comment at i, where each inner `/*` needs its own `*/`."""
    depth = 0
    for delimiter in BLOCK_DELIMITER.finditer(src, i):
        depth += 1 if delimiter.group() == "/*" else -1
        if not depth:
            return delimiter.end()
    raise _unclosed(src, i, "block comment")


def _literal_end(src, i, word, syntax):
    """Index just past the literal that opens at i, where the word at i ends at `word`; None when none opens there."""
    if syntax.raw_string:
        end = RAW_STRINGS[syntax.raw_string](src, i, word)
        if end is not None:
            return end
    if syntax.text_block and src.startswith(TEXT_BLOCK, i):
        return _text_block_end(src, i)
    if src[i] == '"':
        return _close(src, i, i + 1, '"', "string", "\\", one_line=not syntax.multiline_strings)
    if src[i] == "'" and syntax.char_literal == "rust":
        char = RUST_CHAR.match(src, i)
        return char.end() if char else None
    if src[i] == "'":
        return _close(src, i, i + 1, "'", "character literal", "\\", one_line=True)
    return None


def _text_block_end(src, i):
    """Index just past the `\"\"\"` block at i; a closing run of more than three quotes ends with its last quote."""
    end = _close(src, i, i + len(TEXT_BLOCK), TEXT_BLOCK, "text block", "\\")
    while src[end:end + 1] == '"':
        end += 1
    return end


def _backtick_end(src, i, word):
    """Go: a backtick string runs to the next backtick, across lines and with no escapes."""
    return _close(src, i, i + 1, "`", "raw string") if src[i] == "`" else None


def _rust_raw_end(src, i, word):
    """Rust: `r`, `br` or `cr`, hashes and a quote open it; a quote and as many hashes close it."""
    opener = RUST_RAW.match(src, word) if src[i:word] in RUST_RAW_PREFIXES else None
    return _close(src, i, opener.end(), '"' + opener.group(1), "raw string") if opener else None


def _swift_raw_end(src, i, word):
    """Swift: hashes and a quote open it, and it ends on its line unless the quote is three and nothing closes there."""
    opener = SWIFT_RAW.match(src, i)
    if opener is None:
        return None
    hashes = opener.group(1)
    end = _closer_end(src, opener.end(), '"' + hashes, "\\" + hashes, one_line=True)
    if end is None and src.startswith(TEXT_BLOCK, opener.end() - 1):
        return _close(src, i, opener.end() + 2, TEXT_BLOCK + hashes, "raw string", "\\" + hashes)
    if end is None:
        raise _unclosed(src, i, "raw string")
    return end


def _cpp_raw_end(src, i, word):
    """C++: `R`, with an encoding prefix or none, then `"delimiter(` open it; `)delimiter"` closes it."""
    opener = CPP_RAW.match(src, word) if src[i:word] in CPP_RAW_PREFIXES else None
    return _close(src, i, opener.end(), ")" + opener.group(1) + '"', "raw string") if opener else None


RAW_STRINGS = {"backtick": _backtick_end, "rust": _rust_raw_end, "swift": _swift_raw_end, "cpp": _cpp_raw_end}


def _close(src, i, start, closer, what, escape="", one_line=False):
    """Index just past the closer of the literal that opens at i; raises LexError when it never closes."""
    end = _closer_end(src, start, closer, escape, one_line)
    if end is None:
        raise _unclosed(src, i, what)
    return end


def _closer_end(src, j, closer, escape, one_line):
    """Index just past the first `closer` from j that `escape` does not escape; None when none, or none on its line."""
    if not escape and not one_line:
        close = src.find(closer, j)
        return None if close < 0 else close + len(closer)
    while j < len(src):
        if escape and src.startswith(escape, j):
            j += len(escape) + 1
        elif src.startswith(closer, j):
            return j + len(closer)
        elif one_line and src[j] == "\n":
            return None
        else:
            j += 1
    return None


def _unclosed(src, i, what):
    """The error for a literal or comment that opens at i and never closes, on the line it opens."""
    return LexError(src.count("\n", 0, i) + 1, "unterminated %s" % what)
