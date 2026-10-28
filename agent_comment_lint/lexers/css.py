"""CSS: only `/* */` is a comment; quoted strings are content."""
from .base import CODE, COMMENT, STRING, Family, LexError, LineBuilder, Markers, normalized, quoted_end


def lex(text):
    """Lex a stylesheet."""
    src = normalized(text)
    if not src:
        return []
    out = LineBuilder()
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == "\n":
            out.newline(CODE)
            i += 1
        elif src[i:i + 2] == "/*":
            close = src.find("*/", i + 2)
            if close == -1:
                raise LexError(out.lineno, "unterminated block comment")
            out.emit_block_comment(src[i:close + 2])
            i = close + 2
        elif ch in "\"'":
            end = quoted_end(src, i)
            if end is None:
                raise LexError(out.lineno, "unterminated string")
            out.emit_span(STRING, src[i:end])
            i = end
        else:
            out.emit(CODE, ch)
            i += 1
    return out.finish()


# A leading `*` is the universal selector here, so it never continues a comment.
FAMILY = Family("css", (".css",), Markers(hash=False, slash=False, block=True, star=False), lex)
