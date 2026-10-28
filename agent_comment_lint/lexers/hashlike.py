"""Shell, YAML and HCL: `#` comments (HCL also takes C-style ones); heredoc payload is content."""
import re

from .base import Family, LexError, Markers
from .linescan import live_code_hit, scan_lines

# `<<<` is a shell herestring, an unrelated construct one `<` longer than a heredoc opener.
HEREDOC_START = re.compile(r"(?<!<)<<(?!<)[-~]?\s*(['\"]?)([A-Za-z_](?a:\w*))\1")


def _is_shift(raw, hit):
    """True when the `<<` sits inside shell arithmetic, where it shifts bits and opens no heredoc."""
    before = raw[:hit.start()]
    return before.count("((") > before.count("))")


def heredoc_payload(lines, *, slash_marker):
    """Per-line flags for heredoc payload, which is emitted output rather than source."""
    payload = [False] * len(lines)
    terminator = None
    opened_at = 0
    for index, raw in enumerate(lines):
        if terminator is not None:
            if raw.strip() == terminator:
                terminator = None
            else:
                payload[index] = True
            continue
        hit = live_code_hit(raw, HEREDOC_START, hash_marker=True, slash_marker=slash_marker)
        if hit is not None and not _is_shift(raw, hit):
            terminator = hit.group(2)
            opened_at = index + 1
    if terminator is not None:
        raise LexError(opened_at, "unterminated heredoc <<%s: no closing line before end of file" % terminator)
    return payload


def _lexer(*, slash_marker):
    def lex(text):
        lines = text.splitlines()
        payload = heredoc_payload(lines, slash_marker=slash_marker)
        if lines and lines[0].startswith("#!"):
            payload[0] = True
        return scan_lines(lines, payload, [None] * len(lines), hash_marker=True, slash_marker=slash_marker)
    return lex


HASH_ONLY = Markers(hash=True, slash=False, block=False, star=False)

SHELL = Family("shell", (".sh",), HASH_ONLY, _lexer(slash_marker=False))
YAML = Family("yaml", (".yml", ".yaml"), HASH_ONLY, _lexer(slash_marker=False))
HCL = Family("hcl", (".tf", ".tfvars", ".hcl"),
             Markers(hash=True, slash=True, block=True, star=True), _lexer(slash_marker=True))
