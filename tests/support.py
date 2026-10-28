"""Helpers shared by the tests of the named changes."""
from agent_comment_lint import engine
from agent_comment_lint.lexers import family_for


def found(path, text):
    """(rule, line) for every finding in `text`, read as the language `path` names."""
    return [(finding.rule, finding.line) for finding in engine.check_text(path, text).findings]


def comments(path, text):
    """The comment segments of each line, as the lexer for `path` sees them."""
    return [[part for kind, part in (line.segments or ()) if kind == "comment"]
            for line in family_for(path).lex(text)]


LONG = "x" * 130
