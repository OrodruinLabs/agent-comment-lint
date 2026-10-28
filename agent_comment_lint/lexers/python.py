"""Python: `#` comments and docstrings; any other triple-quoted string is content."""
import ast
import re

from .base import BlockLine, Family, LexError, Markers
from .linescan import closing_line, delimited_payload, scan_lines

TRIPLE_OPEN = re.compile(r"""(?<!\\)("{3}|'{3})""")
TRIPLE_QUOTES = ('"""', "'''")
DOCSTRING_HOSTS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
STRING_PREFIX = "rRuU"


def docstring_spans(text):
    """Inclusive (start, end) line spans of every docstring; None when the text does not parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, DOCSTRING_HOSTS) or not node.body:
            continue
        first = node.body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            spans.append((first.lineno, first.end_lineno or first.lineno))
    return spans


def triple_quoted_payload(lines, *, strict):
    """Per-line flags for the lines inside a multi-line triple-quoted string; `strict` refuses an unclosed one."""
    return delimited_payload(lines, TRIPLE_OPEN, hash_marker=True, slash_marker=False,
                             kind="triple-quoted string", strict=strict)


def _triple_opener(stripped):
    """The triple-quote delimiter a stripped line opens with, past any string prefix; None when it opens none."""
    head = stripped.lstrip(STRING_PREFIX)
    for delimiter in TRIPLE_QUOTES:
        if head.startswith(delimiter):
            return delimiter
    return None


def _guessed_close(lines, index, delimiter):
    """Index of the line closing the docstring opened on `index`; None when it never closes."""
    if lines[index].strip().lstrip(STRING_PREFIX).count(delimiter) >= 2:
        return index
    return closing_line(lines, index, delimiter)


def guessed_docstring_spans(lines, payload):
    """Docstrings guessed without a parse: a triple-quote opener at the start or right after a colon line."""
    spans = []
    previous = None
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if payload[index] or not stripped:
            index += 1
            continue
        delimiter = _triple_opener(stripped)
        if delimiter and (previous is None or previous.endswith(":")):
            end = _guessed_close(lines, index, delimiter)
            if end is None:
                raise LexError(index + 1, "unterminated docstring: no closing %s before end of file" % delimiter)
            spans.append((index + 1, end + 1))
            previous = lines[end].strip()
            index = end + 1
            continue
        previous = stripped
        index += 1
    return spans


def _body(raw, opens, closes):
    """A docstring line's prose with the delimiters removed; a delimiter-only line still counts as prose."""
    text = raw.strip()
    if opens:
        text = text.lstrip(STRING_PREFIX)
        for delimiter in TRIPLE_QUOTES:
            if text.startswith(delimiter):
                text = text[len(delimiter):]
                break
    if closes:
        for delimiter in TRIPLE_QUOTES:
            if text.endswith(delimiter):
                text = text[:-len(delimiter)]
                break
    return text.strip() or raw.strip()


def _doc_lines(lines, spans):
    docs = [None] * len(lines)
    for start, end in spans:
        end = min(end, len(lines))
        for number in range(start, end + 1):
            opens, closes = number == start, number == end
            docs[number - 1] = BlockLine(_body(lines[number - 1], opens, closes), opens, closes)
    return docs


def lex(text):
    """Lex Python source; the parser places docstrings when the text parses, a guess when it does not."""
    lines = text.splitlines()
    spans = docstring_spans(text)
    payload = triple_quoted_payload(lines, strict=spans is None)
    if spans is None:
        spans = guessed_docstring_spans(lines, payload)
    if lines and lines[0].startswith("#!"):
        payload[0] = True
    return scan_lines(lines, payload, _doc_lines(lines, spans), hash_marker=True, slash_marker=False)


FAMILY = Family("python", (".py",), Markers(hash=True, slash=False, block=False, star=False), lex)
