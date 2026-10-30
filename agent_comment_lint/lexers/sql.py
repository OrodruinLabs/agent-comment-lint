"""SQL: `--`, `#` and `/* */` comments, read the standard way unless the file shows a MySQL marker."""
import bisect
import re
import string

from .base import CODE, COMMENT, STRING, BlockLine, Family, LexError, LineBuilder, Markers, normalized

# The lexer places every comment line itself, so the rules never read a raw line for a marker of their own.
MARKERS = Markers(hash=False, slash=False, block=False, star=False)

# Code that starts nothing: a `#` before a non-space and a `$` that opens no quote join it; a `;` stands alone.
STANDARD_RUN = re.compile(r"(?:[^\n\-#/'\"`$;]+|-(?!-)|#(?=\S)|/(?!\*)|\$(?!(?:[A-Za-z_][A-Za-z0-9_]*)?\$))*")
# In MySQL a `--` opens a comment only before a space or the end of the line, and a `$` opens nothing.
MYSQL_RUN = re.compile(r"(?:[^\n\-#/'\"`;]+|-(?!-(?:\s|\Z))|/(?!\*))*")
DOLLAR_TAG = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
# Every tag in the file, overlapping ones too: `$a$b$` holds both `$a$` and `$b$`.
DOLLAR_TAGS = re.compile(r"(?=(%s))" % DOLLAR_TAG.pattern)
IDENTIFIER_CHARS = frozenset(string.ascii_letters + string.digits + "_$")
# A closing quote is never followed by another one, which would make the two a quote instead.
QUOTED = {"'": re.compile(r"'[^']*(?:''[^']*)*'(?!')"), '"': re.compile(r'"[^"]*(?:""[^"]*)*"(?!")')}
ESCAPED = {"'": re.compile(r"'[^'\\]*(?:(?:\\.|'')[^'\\]*)*'(?!')", re.S),
           '"': re.compile(r'"[^"\\]*(?:(?:\\.|"")[^"\\]*)*"(?!")', re.S)}
BACKTICK_NAME = re.compile(r"`[^`]*(?:``[^`]*)*`(?!`)")
EXECUTABLE = ("/*!", "/*+")
# A statement that opens with a `#` comment, or with a `DELIMITER` command at the start of a line, is MySQL.
MYSQL_STATEMENT = re.compile(r"[^\S\n]*#\S|(?<![^\n])[^\S\n]*delimiter[^\S\n]+\S", re.I)
COPY_FROM_STDIN = re.compile(r"\s*copy\b.*\bfrom\s+stdin\b", re.I | re.S)
ROWS_END = re.compile(r"^\\\.$", re.M)


class _MySQL(Exception):
    """The standard pass met a MySQL marker outside strings and comments, so the file is read the MySQL way."""


class _Unclosed(Exception):
    """A literal or comment that opens at `start` and never closes; its line is counted only if nothing catches it."""

    def __init__(self, start, what):
        super().__init__(what)
        self.start = start
        self.what = what


def lex(text):
    """Lex SQL; a `/*!` comment or backtick name in code, or a statement opened by `#` or `DELIMITER`, means MySQL."""
    src = normalized(text)
    if not src:
        return []
    try:
        calls, _ = _lex(src, mysql=False)
    except _MySQL:
        calls, _ = _lex(src, mysql=True)
    except LexError as error:
        calls = _mysql_reading(src, error)
    out = LineBuilder()
    for call, *args in calls:
        call(out, *args)
    return out.finish()


def _mysql_reading(src, error):
    """The MySQL reading of a file the standard reading stops in before any marker, kept only if it shows one."""
    try:
        calls, marked = _lex(src, mysql=True)
    except LexError:
        marked = False
    if not marked:
        raise error
    return calls


def _marker(mysql):
    """Note a MySQL marker in code: the standard pass stops there, and the MySQL pass reports that it saw one."""
    if not mysql:
        raise _MySQL
    return True


def _lex(src, mysql):
    """The LineBuilder calls for `src`, recorded so that a dollar-quoted body that does not lex can be taken back."""
    calls = []
    # Each dollar quote open around i: where its body's calls start, its tag, and the bounds outside it.
    frames = []
    # Where each dollar-quote tag occurs, indexed when the first quote opens.
    tags = None
    start, end, i = 0, len(src), 0
    closed_at = -1
    # The code of the statement open at the top level, and whether a `COPY ... FROM stdin;` just ended.
    statement, copying = [], False
    # Whether the line is a psql command such as `\connect db`, which takes no `;` and is part of no statement.
    psql = False
    marked = False
    while i < end or frames:
        if i == end:
            # The body lexed as SQL, so its calls stand and its closing tag ends it.
            _, tag, start, end = frames.pop()
            calls.append((LineBuilder.emit, STRING, tag))
            i += len(tag)
            continue
        try:
            top = not frames and not psql
            if top and not statement and MYSQL_STATEMENT.match(src, i):
                marked = _marker(mysql)
            run = (MYSQL_RUN if mysql else STANDARD_RUN).match(src, i, end).end()
            ch = src[i]
            if top and run == i and ch != ";" and (statement or ch in "'\"`$"):
                # A string, a quoted name or a dollar quote opens the statement; space and comments only part its words.
                statement.append(" ")
            if run > i:
                code = src[i:run]
                calls.append((LineBuilder.emit, CODE, code))
                if top:
                    psql = not statement and code.lstrip().startswith("\\")
                    if not psql and (statement or code.strip()):
                        statement.append(code)
                i = run
            elif ch == ";":
                calls.append((LineBuilder.emit, CODE, ch))
                i += 1
                if top:
                    copying = not mysql and bool(COPY_FROM_STDIN.match("".join(statement)))
                    statement = []
            elif ch == "\n" and copying and not frames:
                # psql reads the lines after `COPY ... FROM stdin;` as table rows, up to a `\.` line or the end.
                rows_end = ROWS_END.search(src, i + 1, end)
                calls.append((LineBuilder.emit_span, STRING, src[i:rows_end.start() - 1 if rows_end else end]))
                if rows_end:
                    # The `\.` line is code, and part of no statement.
                    calls.extend(((LineBuilder.newline, CODE), (LineBuilder.emit, CODE, rows_end.group())))
                i, copying = rows_end.end() if rows_end else end, False
            elif ch == "\n":
                calls.append((LineBuilder.newline, CODE))
                i += 1
                psql = False
            elif ch in "-#":
                i = _line_comment(calls, src, i, end, closed_at)
            elif ch == "/":
                if not frames and src.startswith("/*!", i):
                    marked = _marker(mysql)
                i, spans_lines = _block_comment(calls, src, i, end)
                closed_at = i if spans_lines else closed_at
            elif ch == "`" and frames:
                # A dollar-quoted body is read the standard way, where a backtick is plain code.
                calls.append((LineBuilder.emit, CODE, ch))
                i += 1
            elif ch == "$" and i > start and src[i - 1] in IDENTIFIER_CHARS:
                calls.append((LineBuilder.emit, CODE, ch))
                i += 1
            elif ch == "$":
                tag = DOLLAR_TAG.match(src, i, end).group()
                tags = tags or _dollar_tags(src)
                close = _closing_tag(tags[tag], i + len(tag), end - len(tag))
                if close < 0:
                    raise _Unclosed(i, "dollar quote")
                calls.append((LineBuilder.emit, STRING, tag))
                i += len(tag)
                frames.append((len(calls), tag, start, end))
                start, end = i, close
            else:
                # psql runs the text between backticks on a command line as a shell command.
                if ch == "`" and not psql:
                    marked = _marker(mysql)
                i = _literal(calls, src, i, start, end, mysql)
        except _Unclosed as error:
            if not frames:
                raise LexError(src.count("\n", 0, error.start) + 1, "unterminated %s" % error.what) from None
            # The body does not lex as SQL, so all of it is content and the lines it spans open in a string.
            checkpoint, tag, outer_start, outer_end = frames.pop()
            del calls[checkpoint:]
            calls.append((_string_span, src, start, end + len(tag)))
            start, end, i = outer_start, outer_end, end + len(tag)
    return calls, marked


def _dollar_tags(src):
    """The positions of each dollar-quote tag in src, in order, so that a closing tag is found without a scan."""
    tags = {}
    for found in DOLLAR_TAGS.finditer(src):
        tags.setdefault(found.group(1), []).append(found.start())
    return tags


def _closing_tag(positions, first, last):
    """The first of a tag's positions from `first` to `last`, or -1."""
    k = bisect.bisect_left(positions, first)
    return positions[k] if k < len(positions) and positions[k] <= last else -1


def _string_span(out, src, start, stop):
    """Replay a dollar-quoted body that does not lex as string content, sliced only if no outer body took it back."""
    out.emit_span(STRING, src[start:stop])


def _line_comment(calls, src, i, end, closed_at):
    """Record the `--` or `#` comment at i; after only space, or a block close, it is a line of a C1 block."""
    stop = src.find("\n", i, end)
    stop = end if stop < 0 else stop
    calls.append((LineBuilder.emit, COMMENT, src[i:stop]))
    lead = i
    while lead and src[lead - 1] != "\n" and src[lead - 1].isspace():
        lead -= 1
    if lead == closed_at or not lead or src[lead - 1] == "\n":
        body = src[i + (2 if src[i] == "-" else 1):stop].strip()
        calls.append((LineBuilder.place, BlockLine(body, lead == closed_at, False)))
    return stop


def _block_comment(calls, src, i, end):
    """Record the `/* */` comment at i; return the index past it and whether it is prose that spans lines."""
    close = src.find("*/", i + 2, end)
    if close < 0:
        raise _Unclosed(i, "block comment")
    text = src[i:close + 2]
    if text.startswith(EXECUTABLE):
        # An executable comment or a hint is code, and each line it continues onto opens in a string.
        for index, part in enumerate(text.split("\n")):
            if index:
                calls.append((LineBuilder.newline, STRING))
            calls.append((LineBuilder.emit, CODE, part))
        return close + 2, False
    if "\n" in text:
        calls.append((LineBuilder.emit_block_comment, text))
        return close + 2, True
    calls.append((LineBuilder.emit, COMMENT, text))
    return close + 2, False


def _literal(calls, src, i, start, end, mysql):
    """Record the string or quoted name that opens at i, and return the index just past it."""
    quote = src[i]
    if quote == "`":
        pattern, what = BACKTICK_NAME, "quoted identifier"
    elif mysql or quote == "'" and _e_string(src, i, start):
        pattern, what = ESCAPED[quote], "string"
    else:
        pattern, what = QUOTED[quote], "string" if quote == "'" else "quoted identifier"
    literal = pattern.match(src, i, end)
    if literal is None:
        raise _Unclosed(i, what)
    calls.append((LineBuilder.emit_span, STRING, literal.group()))
    return literal.end()


def _e_string(src, i, start):
    """True for a Postgres `E'...'` string: an `E` that is a word of its own right before the quote."""
    return i > start and src[i - 1] in "Ee" and (i - 1 == start or src[i - 2] not in IDENTIFIER_CHARS)


FAMILY = Family("sql", (".sql",), MARKERS, lex)
