"""JavaScript and TypeScript: strings, template literals and regex literals are content, never comments."""
from .base import CODE, COMMENT, STRING, Family, LexError, LineBuilder, Markers, normalized, quoted_end

# After one of these a `/` cannot be a division, so it opens a regex literal.
REGEX_AFTER_PUNCTUATION = frozenset("(,=:[!&|?{};+-*%>~^")
REGEX_AFTER_WORDS = frozenset((
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else",
    "yield", "await"))
VALUE = "value"
TEMPLATE, EXPRESSION = "template", "expression"


def _is_word_char(ch):
    return ch.isalnum() or ch in "_$" or ord(ch) > 127


def _word_end(src, i):
    while i < len(src) and _is_word_char(src[i]):
        i += 1
    return i


def _regex_end(src, i):
    """Index just past the regex literal opened at i, flags included; None when the slash at i is no regex."""
    j = i + 1
    in_class = False
    while j < len(src):
        ch = src[j]
        if ch == "\n":
            return None
        if ch == "\\":
            j += 2
            continue
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            # A slash that a comment opener follows cannot be closing a regex; the first one divided.
            return None if src[j + 1:j + 2] in ("/", "*") else _word_end(src, j + 1)
        j += 1
    return None


def _regex_may_start(previous):
    """True when a `/` after the previous significant token can only open a regex literal."""
    return previous is None or previous in REGEX_AFTER_WORDS or previous in REGEX_AFTER_PUNCTUATION


def _is_postfix_bang(src, i, previous):
    """True for a non-null `!` glued to the value before it, after which a `/` still divides."""
    if src[i + 1:i + 2] == "=" or i == 0 or src[i - 1].isspace():
        return False
    return previous in (VALUE, ")", "]")


def _lexer(jsx):
    def lex(text):
        return _lex(normalized(text), jsx)
    return lex


def _lex(src, jsx):
    """Walk the source once, tracking template nesting on a stack; a quote JSX text leaves open is plain text."""
    if not src:
        return []
    out = LineBuilder()
    stack = []
    previous = None
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if stack and stack[-1][0] == TEMPLATE:
            if ch == "\\" and src[i + 1:i + 2] not in ("", "\n"):
                out.emit(STRING, src[i:i + 2])
                i += 2
            elif ch == "`":
                out.emit(STRING, ch)
                stack.pop()
                previous = VALUE
                i += 1
            elif ch == "$" and src[i + 1:i + 2] == "{":
                out.emit(STRING, "${")
                stack.append([EXPRESSION, 0])
                previous = "{"
                i += 2
            elif ch == "\n":
                out.newline(STRING)
                i += 1
            else:
                out.emit(STRING, ch)
                i += 1
            continue
        two = src[i:i + 2]
        if ch == "\n":
            out.newline(CODE)
            i += 1
        elif ch.isspace():
            out.emit(CODE, ch)
            i += 1
        elif two == "//":
            end = src.find("\n", i)
            end = n if end == -1 else end
            out.emit(COMMENT, src[i:end])
            i = end
        elif two == "/*":
            close = src.find("*/", i + 2)
            if close == -1:
                raise LexError(out.lineno, "unterminated block comment")
            out.emit_block_comment(src[i:close + 2])
            i = close + 2
        elif ch == "/":
            end = _regex_end(src, i) if _regex_may_start(previous) else None
            if end is None:
                out.emit(CODE, ch)
                previous = ch
                i += 1
            else:
                out.emit(STRING, src[i:end])
                previous = VALUE
                i = end
        elif ch in "\"'":
            end = quoted_end(src, i)
            if end is None and not jsx:
                raise LexError(out.lineno, "unterminated string literal")
            if end is None:
                out.emit(CODE, ch)
                i += 1
            else:
                out.emit_span(STRING, src[i:end])
                i = end
            previous = VALUE
        elif ch == "`":
            out.emit(STRING, ch)
            stack.append([TEMPLATE, out.lineno])
            i += 1
        elif ch == "{":
            if stack:
                stack[-1][1] += 1
            out.emit(CODE, ch)
            previous = ch
            i += 1
        elif ch == "}" and stack and stack[-1][1] == 0:
            stack.pop()
            out.emit(STRING, ch)
            i += 1
        elif ch == "}":
            if stack:
                stack[-1][1] -= 1
            out.emit(CODE, ch)
            previous = ch
            i += 1
        elif _is_word_char(ch):
            end = _word_end(src, i)
            word = src[i:end]
            out.emit(CODE, word)
            previous = word if word in REGEX_AFTER_WORDS else VALUE
            i = end
        elif ch == "!" and _is_postfix_bang(src, i, previous):
            out.emit(CODE, ch)
            i += 1
        else:
            out.emit(CODE, ch)
            previous = ch
            i += 1
    for kind, opened_at in stack:
        if kind == TEMPLATE:
            raise LexError(opened_at, "unterminated template literal")
    return out.finish()


MARKERS = Markers(hash=False, slash=True, block=True, star=False)

SCRIPT = Family("javascript", (".ts", ".mts", ".cts", ".js", ".mjs", ".cjs"), MARKERS, _lexer(jsx=False))
JSX = Family("jsx", (".tsx", ".jsx"), MARKERS, _lexer(jsx=True))
