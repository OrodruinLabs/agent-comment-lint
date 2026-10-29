"""The lexer contract: a language family turns source text into one Line per source line."""
from collections import namedtuple

CODE, STRING, COMMENT = "code", "string", "comment"

BLOCK_OPEN, BLOCK_CLOSE = "/*", "*/"

Line = namedtuple("Line", ["segments", "opens_in", "blocks"], defaults=[()])
Line.__doc__ = "One source line: its (kind, text) segments or None, the state it opens in, and its placed block parts."

BlockLine = namedtuple("BlockLine", ["body", "opens", "closes"])
BlockLine.__doc__ = "A line of a block the lexer placed itself: its prose, and whether it opens or closes the block."

Markers = namedtuple("Markers", ["hash", "slash", "block", "star"])
Markers.__doc__ = "Which markers start a whole-line comment: `#`, `//`, `/*`, and whether a leading `*` continues one."

Family = namedtuple("Family", ["name", "extensions", "markers", "lex", "names"], defaults=[()])
Family.__doc__ = "A language family: its extensions, exact file names, comment markers and `lex(text) -> [Line]`."


class LexError(Exception):
    """The text cannot be lexed safely, so no verdict on it would be honest."""

    def __init__(self, line, message):
        super().__init__("line %d: %s" % (line, message))
        self.line = line
        self.message = message


class LineBuilder:
    """Collects segments into Lines for the lexers that walk the text one character at a time."""

    def __init__(self):
        self.lines = []
        self.lineno = 1
        self._segments = []
        self._opens_in = CODE
        self._blocks = []

    def emit(self, kind, text):
        """Append text to the current line, merging with a preceding segment of the same kind."""
        if not text:
            return
        if self._segments and self._segments[-1][0] == kind:
            self._segments[-1] = (kind, self._segments[-1][1] + text)
        else:
            self._segments.append((kind, text))

    def newline(self, opens_in):
        """Close the current line; `opens_in` is the state the next line starts in."""
        self.lines.append(Line(self._segments, self._opens_in, tuple(self._blocks)))
        self._segments = []
        self._opens_in = opens_in
        self._blocks = []
        self.lineno += 1

    def emit_span(self, kind, text):
        """Append text that may cross line breaks; every line it continues onto opens in `kind`."""
        parts = text.split("\n")
        self.emit(kind, parts[0])
        for part in parts[1:]:
            self.newline(kind)
            self.emit(kind, part)

    def place(self, block):
        """Place one BlockLine on the current line, for a block the lexer finds by its own rules."""
        self._blocks.append(block)

    def emit_block_comment(self, text):
        """Append one whole `/* */` comment; when it crosses line breaks, each of its lines is placed in one block."""
        parts = text.split("\n")
        last = len(parts) - 1
        for index, part in enumerate(parts):
            if index:
                self.newline(COMMENT)
            self.emit(COMMENT, part)
            if last:
                opens, closes = index == 0, index == last
                self._blocks.append(BlockLine(_block_comment_body(part, opens, closes), opens, closes))

    def finish(self):
        """Close the last line and return every Line."""
        self.lines.append(Line(self._segments, self._opens_in, tuple(self._blocks)))
        return self.lines


def block_prose(text):
    """The prose of one line of a `/* */` comment, once its delimiters are cut off: no leading `*`, no outer space."""
    return text.lstrip("*").strip()


def _block_comment_body(part, opens, closes):
    """The prose one line of a lexer-placed `/* */` comment holds."""
    if opens:
        return block_prose(part[len(BLOCK_OPEN):])
    return block_prose((part[:-len(BLOCK_CLOSE)] if closes else part).strip())


def quoted_end(src, i):
    """Index just past the string opened at i; None when it reaches the end of its line unclosed."""
    quote = src[i]
    j = i + 1
    while j < len(src):
        ch = src[j]
        if ch == "\\":
            j += 2
        elif ch == quote:
            return j + 1
        elif ch == "\n":
            return None
        else:
            j += 1
    return None


def normalized(text):
    """The text with every line break `str.splitlines` knows reduced to a newline, and no final break."""
    return "\n".join(text.splitlines())
