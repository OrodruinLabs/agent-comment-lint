"""Judging one file: pick its lexer by extension, lex the text, apply the rules. No I/O."""
from collections import namedtuple

from . import rules
from .governance import DEFAULT
from .lexers import family_for

FileResult = namedtuple("FileResult", ["findings", "unresolved_lines"])
FileResult.__doc__ = "The findings for one file, and how many of its lines the line lexers left unjudged."


def in_scope(path):
    """True when the path's extension belongs to a covered language."""
    return family_for(path) is not None


def check_text(path, text, governance=DEFAULT):
    """Every finding in `text`, read as the language `path` names; raises LexError when it cannot be lexed."""
    family = family_for(path)
    if family is None:
        raise ValueError("%s: not a covered file type" % path)
    raw_lines = text.splitlines()
    lexed = family.lex(text)
    return FileResult(rules.check(raw_lines, lexed, family.markers, governance), rules.unresolved_lines(lexed))


def within(findings, ranges):
    """The findings whose line span overlaps one of the inclusive (start, end) ranges."""
    return [finding for finding in findings
            if any(finding.line <= end and start <= finding.end_line for start, end in ranges)]
