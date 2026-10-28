"""Claude Code's PreToolUse event: the file a write would leave behind, and which of its lines the write touched."""
import difflib
from collections import namedtuple

WRITE_TOOLS = ("Write", "Edit", "MultiEdit")

Target = namedtuple("Target", ["tool", "path", "tool_input"])
Target.__doc__ = "A write the hook judges: the tool's name, the file it writes, and the tool's own input."


class HookInputError(Exception):
    """Standard input is not the event Claude Code sends, so the hook cannot tell what is being written."""


def target(event):
    """The write an event proposes; None for a tool that writes no file the hook judges."""
    if not isinstance(event, dict):
        raise HookInputError("expected a JSON object")
    tool = event.get("tool_name")
    if not isinstance(tool, str):
        raise HookInputError("no \"tool_name\"")
    if tool not in WRITE_TOOLS:
        return None
    tool_input = event.get("tool_input")
    path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(path, str) or not path:
        raise HookInputError("%s with no \"tool_input.file_path\"" % tool)
    return Target(tool, path, tool_input)


def _string(value, name):
    if not isinstance(value, str):
        raise HookInputError("\"%s\" is not a string" % name)
    return value


def _replaced(text, old, new, replace_all):
    """What one edit leaves; None where the edit tool itself refuses it, so there is nothing to judge."""
    if old == "":
        # An empty old string only creates a file, or fills an empty one.
        return new if not text else None
    if text is None:
        return None
    count = text.count(old)
    if count == 0 or (count > 1 and not replace_all):
        return None
    return text.replace(old, new) if replace_all else text.replace(old, new, 1)


def _edited(text, old, new, replace_all):
    """One edit, matched exactly, else the way the tool does for a file with Windows line endings."""
    result = _replaced(text, old, new, replace_all)
    if result is not None or not text or "\r\n" not in text:
        return result
    # The tool matches a CRLF file as if it used \n only, so its strings carry no \r.
    result = _replaced(text.replace("\r\n", "\n"), old.replace("\r\n", "\n"), new.replace("\r\n", "\n"), replace_all)
    return None if result is None else result.replace("\n", "\r\n")


def proposed_text(target, current):
    """The file's text after the write; None where the tool would refuse it. `current` is None for a missing file."""
    tool_input = target.tool_input
    if target.tool == "Write":
        return _string(tool_input.get("content"), "content")
    edits = [tool_input] if target.tool == "Edit" else tool_input.get("edits")
    if not isinstance(edits, list):
        raise HookInputError("MultiEdit with no \"edits\" list")
    text = current
    for edit in edits:
        if not isinstance(edit, dict):
            raise HookInputError("an edit is not a JSON object")
        replace_all = edit.get("replace_all", False)
        if not isinstance(replace_all, bool):
            raise HookInputError("\"replace_all\" is not a boolean")
        text = _edited(text, _string(edit.get("old_string"), "old_string"),
                       _string(edit.get("new_string"), "new_string"), replace_all)
        if text is None:
            return None
    return text


def changed_ranges(before, after):
    """Inclusive (start, end) line ranges of `after` that the write added or changed, as a line diff finds them."""
    matcher = difflib.SequenceMatcher(None, (before or "").splitlines(), after.splitlines(), autojunk=False)
    return [(first + 1, last) for tag, _i1, _i2, first, last in matcher.get_opcodes() if tag in ("replace", "insert")]
