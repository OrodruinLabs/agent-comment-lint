"""Ruby: `#` comments, `=begin`/`=end` blocks; heredoc payload and the data after `__END__` are content."""
import re

from .base import BlockLine, Family, LexError
from .hashlike import HASH_ONLY
from .linescan import live_code_hit, scan_lines

# An opener follows a line start, a space or one of `(,=[{!&|;`, maybe through a unary sign; never a word or a `:`.
HEREDOC_START = re.compile(r"(?:^|(?<=[\s(,=\[{!&|;]))[+-]?<<([-~]?)(['\"]?)([A-Za-z_](?a:\w*))\2")
# `class <<self` opens the singleton class, never a heredoc.
SINGLETON_CLASS = re.compile(r"(?<![\w.])class\s+$")
DATA_SECTION = "__END__"
BEGIN_LINE = re.compile(r"=begin(?:\s|$)")
END_LINE = re.compile(r"=end(?:\s|$)")


def _closes_heredoc(raw, indent_ok, terminator):
    return (raw.strip() if indent_ok else raw) == terminator


def _block_body(raw, opens, closes):
    return "" if opens or closes else raw.strip()


def ruby_regions(lines):
    """(payload, docs): flags for heredoc and `__END__` data lines, and BlockLine entries for `=begin` block lines."""
    payload = [False] * len(lines)
    docs = [None] * len(lines)
    heredoc = None
    block_from = None
    for index, raw in enumerate(lines):
        if heredoc is not None:
            if _closes_heredoc(raw, *heredoc[:2]):
                heredoc = None
            else:
                payload[index] = True
            continue
        if block_from is not None:
            closes = bool(END_LINE.match(raw))
            docs[index] = BlockLine(_block_body(raw, False, closes), False, closes)
            if closes:
                block_from = None
            continue
        if raw == DATA_SECTION:
            payload[index + 1:] = [True] * (len(lines) - index - 1)
            break
        if BEGIN_LINE.match(raw):
            block_from = index + 1
            docs[index] = BlockLine("", True, False)
            continue
        hit = live_code_hit(raw, HEREDOC_START, hash_marker=True, slash_marker=False)
        if hit is not None and not SINGLETON_CLASS.search(raw, 0, hit.start()):
            heredoc = (hit.group(1) != "", hit.group(3), index + 1)
    if heredoc is not None:
        raise LexError(heredoc[2], "unterminated heredoc <<%s: no closing line before end of file" % heredoc[1])
    if block_from is not None:
        raise LexError(block_from, "unterminated =begin block: no =end before end of file")
    return payload, docs


def lex(text):
    """Lex Ruby source one line at a time."""
    lines = text.splitlines()
    payload, docs = ruby_regions(lines)
    if lines and lines[0].startswith("#!"):
        payload[0] = True
    return scan_lines(lines, payload, docs, hash_marker=True, slash_marker=False)


FAMILY = Family("ruby", (".rb", ".rake", ".gemspec"), HASH_ONLY, lex, ("Gemfile", "Rakefile"))
