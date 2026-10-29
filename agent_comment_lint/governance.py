"""The governance references no comment may carry: a fixed core, opt-in packs, and a repository's own additions."""
import re
from collections import namedtuple

# Two uppercase hex digits carrying at least one A-F, so the `09` in a zero-padded reference is not read as a byte.
HEX_BYTE = r"(?:[0-9A-F][A-F]|[A-F][0-9A-F])"

# `Dn` names a decision only outside a hex-byte run, where the same shape names a byte.
DECISION_REF = r"(?<!\b%s )\bD\d{1,2}[a-z-]*\b(?! %s\b)" % (HEX_BYTE, HEX_BYTE)

# A prefix, a dash, one class letter and a number: the shape many planning documents give their task ids.
TASK_ID = r"\b[A-Z]{2,5}-[A-Z]\d{2,}[a-z]?\b"

# A bare `#123` is deliberately absent: colours, HTML entities and upstream issue numbers share the shape.
WORK_ITEM = (r"(?i:\b(?:work[ -]item|user story|story) #?\d{3,}\b)"
             r"|(?i:\b(?:bug|ticket|issue|task) #\d+\b)")

# Case-insensitive only where the token is long enough to disambiguate itself without case.
CORE = (
    r"ADR-\d+",
    r"\bAC-[A-Z]?\d+(?:\.\d+)*",
    r"\bAC\d+\b",
    r"\bFEAT-[0-9A-Z][\w-]*",
    r"\bPATCH-\d+",
    r"\bTRD-\d+[a-z]*",
    r"\bTC-\d+",
    r"\bPRD-\d+",
    r"\bTASK-\d+",
    r"\bDEF-\d+",
    r"\bPR[- ]\d+",
    r"\b(?i:TEST-PLAN)",
    r"\b(?i:threads?[ -]\d{4,})",
    WORK_ITEM,
    r"(?i:docs/[\w./-]+)",
    r"(?i:(?:CLAUDE|AGENTS)\.md)",
)

# An upper-case notes file with a .md suffix, excluding the well-known files that a repository ships.
NOTES_FILE = (r"\b(?!(?:README|CHANGELOG|LICENSE|CONTRIBUTING|SECURITY|CODE_OF_CONDUCT|CLAUDE|AGENTS)\.md\b)"
              r"[A-Z][A-Z0-9_]+\.md\b")

# The plan, chat and review citations that an agent leaves in a comment, one shape per pattern.
AGENT_CONTEXT = (
    r"\bTask \d+\b",
    r"(?i:\bstep \d+ (?:of|in) the plan\b)",
    r"(?i:\bper (?:the )?(?:(?:code )?review|plan|spec)\b)",
    r"(?i:\bas (?:requested|discussed|agreed)\b)",
    r"(?i:\bthe user (?:asked|requested)\b)",
    NOTES_FILE,
)

PACKS = {
    "agent-context": AGENT_CONTEXT,
    "azure-boards": (r"AB#\d+", r"(?i:\bADO #?\d{3,}\b)"),
    "decision-ids": (r"\bD-\d+[a-z-]*", DECISION_REF),
    "task-ids": (TASK_ID,),
}

Extra = namedtuple("Extra", ["pattern", "reason", "regex"])
Extra.__doc__ = "A repository's own governance pattern: its source, why it is there, and its compiled form."


class Matcher(namedtuple("Matcher", ["packs", "extras", "regex"])):
    """The governance list one repository is judged by: the core, its packs and its extras."""

    def first_reference(self, comment):
        """The leftmost governance reference in a comment's text, or None."""
        hits = [hit for hit in [self.regex.search(comment)] + [extra.regex.search(comment) for extra in self.extras]
                if hit]
        return min(hits, key=lambda hit: hit.start()).group(0) if hits else None


def matcher(packs=(), extras=()):
    """The Matcher for the core plus the named packs and the given Extras; raises KeyError for an unknown pack."""
    patterns = CORE + tuple(pattern for name in packs for pattern in PACKS[name])
    return Matcher(tuple(packs), tuple(extras), re.compile("|".join(patterns)))


DEFAULT = matcher()


def first_reference(comment, governance=DEFAULT):
    """The first governance reference in a comment's text, or None."""
    return governance.first_reference(comment)
