"""Makefile: `#` comments in make syntax, shell rules in the recipes of an open rule, `define` blocks as content."""
import re

from .base import CODE, COMMENT, STRING, BlockLine, Family, LexError, Line, LineBuilder
from .hashlike import HASH_ONLY

DEFINE = re.compile(r"\s*(?:(?:override|export|private)\s+)*define(?:\s+(?![\s:?+!]*=)|$)")
# Inside a `define` body make counts only a bare `define` as nested.
NESTED_DEFINE = re.compile(r"\s*define(?:\s|$)")
ENDEF = re.compile(r"\s*endef(?=\s|#|$)")
CONDITIONAL = re.compile(r"\s*(?:ifeq|ifneq|ifdef|ifndef|else|endif)(?:\s+(?![\s:?+!]*=)|$)")
DIRECTIVES = ("define", "undefine", "include", "-include", "sinclude", "export", "unexport", "override", "private",
              "vpath", "load", "-load")
# `=`, `:=`, `::=`, `:::=`, `?=`, `+=` and `!=`.
ASSIGNMENT = re.compile(r":{0,3}=|[?+!]=")
# Make strips blanks and the `@`, `-` and `+` prefixes before the shell sees a recipe line.
RECIPE_PREFIX = re.compile(r"\t[ \t@+-]*")
CLOSERS = {"(": ")", "{": "}"}
# A shell `#` starts a comment only where a word could start.
WORD_START = " \t\n;|&()<>"


def _continues(raw):
    """True when the line ends in an odd run of backslashes, so the next line belongs to it."""
    return (len(raw) - len(raw.rstrip("\\"))) % 2 == 1


def _emit_comment(out, text, i):
    """Emit the make comment that starts at i; a continued one places each of its lines as a part of one block."""
    comment = text[i:]
    if "\n" not in comment:
        out.emit(COMMENT, comment)
        return
    after_code = bool(text[text.rfind("\n", 0, i) + 1:i].strip())
    for index, part in enumerate(comment.split("\n")):
        if index:
            out.newline(COMMENT)
        out.emit(COMMENT, part)
        out.place(BlockLine((part if index else part[1:]).strip(), after_code and not index, False))


def _scan_make(out, text):
    """Make syntax: an unescaped `#` outside a reference starts a comment; returns the code outside references."""
    refs = []
    bare = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        start, outside = i, not refs
        if ch == "\\":
            j = i
            while j < n and text[j] == "\\":
                j += 1
            if (j - i) % 2 and text[j:j + 1] == "#":
                j += 1
            out.emit(CODE, text[i:j])
            i = j
        elif ch == "\n":
            out.newline(STRING if refs else CODE)
            i += 1
        elif ch == "$" and text[i + 1:i + 2] == "$":
            out.emit(CODE, "$$")
            i += 2
        elif ch == "$" and text[i + 1:i + 2] in CLOSERS:
            refs.append((text[i + 1], out.lineno))
            out.emit(CODE, text[i:i + 2])
            i += 2
        elif refs and ch == refs[-1][0]:
            refs.append((ch, out.lineno))
            out.emit(CODE, ch)
            i += 1
        elif refs and ch == CLOSERS[refs[-1][0]]:
            refs.pop()
            out.emit(CODE, ch)
            i += 1
        elif ch == "#" and not refs:
            _emit_comment(out, text, i)
            break
        else:
            out.emit(CODE, ch)
            i += 1
        if outside:
            bare.append(text[start:i])
    if refs:
        raise LexError(refs[0][1], "unterminated variable reference: no closing %s" % CLOSERS[refs[0][0]])
    return "".join(bare)


def _opens_rule(bare):
    """True when a `:` comes before every assignment operator and what follows it is not a target variable."""
    colon = bare.find(":")
    assignment = ASSIGNMENT.search(bare)
    if colon < 0 or (assignment and assignment.start() <= colon):
        return False
    after = bare[colon + 1:]
    after = after[1:] if after.startswith(":") else after
    return not ASSIGNMENT.search(after.split(";", 1)[0])


def _rule_open_after(bare, rule_open):
    """Whether a rule is open after a make line, read from its text outside references and comments."""
    if not bare.strip() or CONDITIONAL.match(bare):
        return rule_open
    if bare.split(None, 1)[0] in DIRECTIVES:
        return False
    return _opens_rule(bare)


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


def _scan_recipe(out, text):
    """Shell rules after make's prefix: quotes protect `#`, and `#` is a comment only at the start of a word."""
    start = i = RECIPE_PREFIX.match(text).end()
    out.emit(CODE, text[:start])
    n = len(text)
    prev = "\t"
    while i < n:
        ch = text[i]
        if ch == "\\" and text[i + 1:i + 2] == "\n":
            out.emit(CODE, ch)
            # A `#` that the continuation carries into the middle of a word is code, so its line is no comment line.
            out.newline(STRING if prev not in WORD_START and text[i + 2:i + 3] == "#" else CODE)
            i += 2
        elif ch == "\\":
            out.emit(CODE, text[i:i + 2])
            prev = "\\"
            i += 2
        elif ch == "\n":
            out.newline(CODE)
            prev = ch
            i += 1
        elif ch == "$" and text[i + 1:i + 2] == "$":
            out.emit(CODE, "$$")
            prev = "$"
            i += 2
        elif ch == "$" and text[i + 1:i + 2] in CLOSERS:
            end = _reference_end(text, i, out.lineno)
            # Make expands a reference before the shell runs, so it is content, and so are the lines it spans.
            out.emit_span(STRING, text[i:end])
            prev = "$"
            i = end
        elif ch in "'\"":
            end = _quote_end(text, i)
            if end is None:
                raise LexError(out.lineno, "unterminated quote %s: no closing quote before end of line" % ch)
            out.emit_span(STRING, text[i:end])
            prev = ch
            i = end
        elif ch == "#" and prev in WORD_START:
            end = text.find("\n", i)
            end = n if end == -1 else end
            out.emit(COMMENT, text[i:end])
            if i == start and text[:start].strip():
                # Behind a prefix the comment fills the line the shell sees, so it joins a block as a comment line does.
                out.place(BlockLine(text[i + 1:end].strip(), False, False))
            i = end
        else:
            out.emit(CODE, ch)
            prev = ch
            i += 1


def _logical_end(lines, start):
    """Index of the last physical line of the logical line that starts at `start`."""
    end = start
    while _continues(lines[end]) and end + 1 < len(lines):
        end += 1
    return end


def lex(text):
    """Lex a Makefile one logical line at a time, tracking `define` blocks and whether a rule is open."""
    lines = text.splitlines()
    if not lines:
        return []
    out = LineBuilder()
    defines = []
    # A tab line is a recipe only while a rule is open; anywhere else it is make syntax.
    rule_open = False
    i = 0
    while i < len(lines):
        if i:
            out.newline(STRING if defines else CODE)
        raw = lines[i]
        if defines:
            # Make never reads a tab line in a body as `define` or `endef`.
            if raw.startswith("\t") or not (ENDEF.match(raw) or NESTED_DEFINE.match(raw)):
                out.emit(CODE, raw)
            elif ENDEF.match(raw):
                _scan_make(out, raw)
                defines.pop()
            else:
                _scan_make(out, raw)
                defines.append(i + 1)
            i += 1
            continue
        end = _logical_end(lines, i)
        body = "\n".join(lines[i:end + 1])
        if rule_open and raw.startswith("\t"):
            _scan_recipe(out, body)
        elif DEFINE.match(raw):
            _scan_make(out, body)
            defines.append(i + 1)
            rule_open = False
        else:
            rule_open = _rule_open_after(_scan_make(out, body), rule_open)
        i = end + 1
    if defines:
        raise LexError(defines[0], "unterminated define: no endef before end of file")
    lexed = out.finish()
    if lines[0].startswith("#!"):
        lexed[0] = Line([(CODE, lines[0])], STRING)
    return lexed


FAMILY = Family("makefile", (".mk",), HASH_ONLY, lex, ("Makefile", "makefile", "GNUmakefile"))
