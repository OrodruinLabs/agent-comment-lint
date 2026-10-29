"""Claude Code's PreToolUse event: the file a write would leave behind, and which of its lines the write touched."""
import difflib
import os
from collections import namedtuple

from . import codex_patch
from .codex_patch import CodexFile, CodexHunk, apply_hunks as apply_codex_hunks

WRITE_TOOLS = ("Write", "Edit", "MultiEdit")

Target = namedtuple("Target", ["tool", "path", "tool_input", "must_apply", "source"], defaults=[False, None])
Target.__doc__ = ("A write the hook judges: the tool's name, the file it writes, the tool's own input, whether an "
                  "edit that does not apply to the file on disk is an error, and the file the edit applies to when "
                  "that is not the one written, as for a move.")


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


def _claude(event):
    found = target(event)
    return [] if found is None else [found]


def parse_codex_patch(text):
    """The files a Codex patch adds, updates and deletes; HookInputError for a patch Codex itself refuses."""
    try:
        return codex_patch.parse_patch(text)
    except codex_patch.PatchError as error:
        raise HookInputError("apply_patch: %s" % error)


def _codex_path(cwd, path):
    """A patch's path as Codex resolves it: a relative one from the session's directory, when the event names one."""
    return os.path.join(cwd, path) if isinstance(cwd, str) and cwd else path


def _codex(event):
    """Codex's apply_patch: one target per file the patch adds or updates; a deleted file is not judged."""
    tool = event.get("tool_name")
    if not isinstance(tool, str):
        raise HookInputError("no \"tool_name\"")
    # A patch Codex intercepts from a shell command reaches hooks as Bash, so it is not judged here.
    if tool != "apply_patch":
        return []
    tool_input = event.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        raise HookInputError("apply_patch with no \"tool_input.command\"")
    cwd = event.get("cwd")
    found = []
    named, moved_to = set(), set()
    for change in parse_codex_patch(command):
        path = _codex_path(cwd, change.path)
        key = os.path.normpath(path)
        # Codex refuses a second operation on a path, yet updates a file an earlier move wrote, which disk cannot show.
        if key in named or (change.kind == "update" and key in moved_to):
            raise HookInputError("apply_patch: more than one operation targets %s" % change.path)
        named.add(key)
        if change.kind == "add":
            found.append(Target("Write", path, {"file_path": path, "content": change.content}))
        elif change.kind == "update" and change.move_to is None:
            found.append(Target("CodexPatch", path, {"file_path": path, "hunks": change.hunks}, True))
        elif change.kind == "update":
            destination = _codex_path(cwd, change.move_to)
            moved_to.add(os.path.normpath(destination))
            found.append(Target("CodexPatch", destination, {"file_path": path, "hunks": change.hunks}, True, path))
    return found


def _windsurf(event):
    """Cascade's pre_write_code: its edits applied exactly, because how Windsurf resolves them is undocumented."""
    action = event.get("agent_action_name")
    if not isinstance(action, str):
        raise HookInputError("no \"agent_action_name\"")
    if action != "pre_write_code":
        return []
    info = event.get("tool_info")
    path = info.get("file_path") if isinstance(info, dict) else None
    if not isinstance(path, str) or not path:
        raise HookInputError("pre_write_code with no \"tool_info.file_path\"")
    edits = info.get("edits")
    if not isinstance(edits, list):
        raise HookInputError("pre_write_code with no \"tool_info.edits\" list")
    return [Target("MultiEdit", path, {"file_path": path, "edits": edits}, must_apply=True)]


def _gemini(event):
    """Gemini CLI's BeforeTool for write_file and replace; a replace must apply exactly, as Gemini may fix its match."""
    name = event.get("hook_event_name")
    if not isinstance(name, str):
        raise HookInputError("no \"hook_event_name\"")
    tool = event.get("tool_name")
    if not isinstance(tool, str):
        raise HookInputError("no \"tool_name\"")
    if name != "BeforeTool" or tool not in ("write_file", "replace"):
        return []
    info = event.get("tool_input")
    path = info.get("file_path") if isinstance(info, dict) else None
    if not isinstance(path, str) or not path:
        raise HookInputError("%s with no \"tool_input.file_path\"" % tool)
    path = _codex_path(event.get("cwd"), path)
    if tool == "write_file":
        return [Target("Write", path, {"file_path": path, "content": info.get("content")})]
    replace_all = info.get("allow_multiple", False)
    if not isinstance(replace_all, bool):
        raise HookInputError("\"allow_multiple\" is not a boolean")
    edit = {"file_path": path, "old_string": info.get("old_string"), "new_string": info.get("new_string"),
            "replace_all": replace_all}
    return [Target("Edit", path, edit, must_apply=True)]


ADAPTERS = {"claude": _claude, "codex": _codex, "windsurf": _windsurf, "gemini": _gemini}
TITLES = {"claude": "Claude Code", "codex": "Codex", "windsurf": "Windsurf", "gemini": "Gemini CLI"}


def targets(event, agent):
    """The writes an agent's event proposes, which is none for an event that writes no file the hook judges."""
    if not isinstance(event, dict):
        raise HookInputError("expected a JSON object")
    return ADAPTERS[agent](event)


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
    if target.tool == "CodexPatch":
        return None if current is None else apply_codex_hunks(current, tool_input["hunks"])
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
    old, new = (before or "").splitlines(), after.splitlines()
    shared = min(len(old), len(new))
    head = 0
    while head < shared and old[head] == new[head]:
        head += 1
    tail = 0
    while tail < shared - head and old[-1 - tail] == new[-1 - tail]:
        tail += 1
    matcher = difflib.SequenceMatcher(None, old[head:len(old) - tail], new[head:len(new) - tail], autojunk=False)
    return [(head + first + 1, head + last) for tag, _i1, _i2, first, last in matcher.get_opcodes()
            if tag in ("replace", "insert")]
