"""Makefile: `#` comments in make syntax, shell rules in recipes, `define` blocks as content."""
import re

from .base import CODE, COMMENT, STRING, Family, LexError, Line
from .hashlike import HASH_ONLY

DEFINE = re.compile(r"\s*(?:(?:override|export|private)\s+)*define(?:\s+(?![\s:?+!]*=)|$)")
ENDEF = re.compile(r"\s*endef(?=\s|#|$)")
CLOSERS = {"(": ")", "{": "}"}
# A shell `#` starts a comment only where a word could start.
WORD_START = " \t\n;|&()<>"


class _Group:
    """The lines of one logical line, collected as segments with the state each opens in."""

    def __init__(self, number, opens_in):
        self.number = number
        self.rows = [[]]
        self.opens = [opens_in]

    @property
    def lineno(self):
        return self.number + len(self.rows) - 1

    def add(self, kind, text):
        if not text:
            return
        row = self.rows[-1]
        if row and row[-1][0] == kind:
            row[-1] = (kind, row[-1][1] + text)
        else:
            row.append((kind, text))

    def span(self, kind, text, carry):
        """Append text that may cross line breaks; each line it continues onto opens in `carry`."""
        parts = text.split("\n")
        self.add(kind, parts[0])
        for part in parts[1:]:
            self.rows.append([])
            self.opens.append(carry)
            self.add(kind, part)

    def lines(self):
        return [Line(row, opens) for row, opens in zip(self.rows, self.opens)]


def _continues(raw):
    """True when the line ends in an odd run of backslashes, so the next line belongs to it."""
    return (len(raw) - len(raw.rstrip("\\"))) % 2 == 1


def _scan_make(group, text):
    """Make syntax: any unescaped `#` outside a `$(...)` or `${...}` reference starts a comment."""
    refs = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            j = i
            while j < n and text[j] == "\\":
                j += 1
            if (j - i) % 2 and text[j:j + 1] == "#":
                j += 1
            group.add(CODE, text[i:j])
            i = j
        elif ch == "\n":
            group.span(CODE, ch, CODE)
            i += 1
        elif ch == "$" and text[i + 1:i + 2] == "$":
            group.add(CODE, "$$")
            i += 2
        elif ch == "$" and text[i + 1:i + 2] in CLOSERS:
            refs.append((text[i + 1], group.lineno))
            group.add(CODE, text[i:i + 2])
            i += 2
        elif refs and ch == refs[-1][0]:
            refs.append((ch, group.lineno))
            group.add(CODE, ch)
            i += 1
        elif refs and ch == CLOSERS[refs[-1][0]]:
            refs.pop()
            group.add(CODE, ch)
            i += 1
        elif ch == "#" and not refs:
            group.span(COMMENT, text[i:], COMMENT)
            return
        else:
            group.add(CODE, ch)
            i += 1
    if refs:
        raise LexError(refs[0][1], "unterminated variable reference: no closing %s" % CLOSERS[refs[0][0]])


def _reference_end(text, i, lineno):
    """Index just past the `$(...)` or `${...}` reference opened at i."""
    opener = text[i + 1]
    depth = 0
    for j in range(i + 1, len(text)):
        if text[j] == opener:
            depth += 1
        elif text[j] == CLOSERS[opener]:
            depth -= 1
            if depth == 0:
                return j + 1
    raise LexError(lineno, "unterminated variable reference: no closing %s" % CLOSERS[opener])


def _quote_end(text, i):
    """Index just past the shell string opened at i; None when it never closes."""
    quote = text[i]
    j = i + 1
    while j < len(text):
        if text[j] == "\\" and quote == '"':
            j += 2
        elif text[j] == quote:
            return j + 1
        else:
            j += 1
    return None


def _scan_recipe(group, text):
    """Shell rules: quotes protect `#`, and `#` is a comment only at the start of a word."""
    i = 0
    n = len(text)
    prev = "\t"
    while i < n:
        ch = text[i]
        if ch == "\\":
            group.span(CODE, text[i:i + 2], CODE)
            if text[i + 1:i + 2] != "\n":
                prev = "\\"
            i += 2
        elif ch == "\n":
            group.span(CODE, ch, CODE)
            prev = ch
            i += 1
        elif ch == "$" and text[i + 1:i + 2] == "$":
            group.add(CODE, "$$")
            prev = "$"
            i += 2
        elif ch == "$" and text[i + 1:i + 2] in CLOSERS:
            end = _reference_end(text, i, group.lineno)
            group.span(CODE, text[i:end], CODE)
            prev = "$"
            i = end
        elif ch in "'\"":
            end = _quote_end(text, i)
            if end is None:
                raise LexError(group.lineno, "unterminated quote %s: no closing quote before end of line" % ch)
            group.span(STRING, text[i:end], STRING)
            prev = ch
            i = end
        elif ch == "#" and prev in WORD_START:
            end = text.find("\n", i)
            end = n if end == -1 else end
            group.add(COMMENT, text[i:end])
            i = end
        else:
            group.add(CODE, ch)
            prev = ch
            i += 1


def _logical_end(lines, start):
    """Index of the last physical line of the logical line that starts at `start`."""
    end = start
    while _continues(lines[end]) and end + 1 < len(lines):
        end += 1
    return end


def lex(text):
    """Lex a Makefile one logical line at a time, tracking `define` blocks."""
    lines = text.splitlines()
    out = []
    defines = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        if defines:
            if ENDEF.match(raw) or DEFINE.match(raw):
                group = _Group(i + 1, STRING)
                _scan_make(group, raw)
                out.extend(group.lines())
                if ENDEF.match(raw):
                    defines.pop()
                else:
                    defines.append(i + 1)
            else:
                out.append(Line([(CODE, raw)] if raw else [], STRING))
            i += 1
            continue
        end = _logical_end(lines, i)
        group = _Group(i + 1, CODE)
        body = "\n".join(lines[i:end + 1])
        if raw.startswith("\t"):
            _scan_recipe(group, body)
        else:
            _scan_make(group, body)
            if DEFINE.match(raw):
                defines.append(i + 1)
        out.extend(group.lines())
        i = end + 1
    if defines:
        raise LexError(defines[0], "unterminated define: no endef before end of file")
    return out


FAMILY = Family("makefile", (".mk",), HASH_ONLY, lex, ("Makefile", "makefile", "GNUmakefile"))
