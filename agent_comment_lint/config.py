"""A repository's settings: paths the policy does not judge, and governance it adds. Each entry gives its reason."""
import json
import re
from collections import namedtuple

from . import governance

CONFIG_NAME = ".agent-comment-lint.json"

# Build output, dependencies and tool state: never authored by hand in any repository.
DEFAULT_SKIP_DIRS = frozenset((
    "node_modules", "bin", "obj", ".terraform", "dist", "build", "coverage", ".git", ".claude", "generated",
    "Migrations", ".venv", "venv", "__pycache__", ".pytest_cache"))
DEFAULT_SKIP_FILES = frozenset((".terraform.lock.hcl",))

Config = namedtuple("Config", ["exclusions", "governance"])
Config.__doc__ = "Parsed settings: (pattern, reason, compiled regex) per exclusion, and the governance Matcher."

EMPTY = Config((), governance.DEFAULT)


class ConfigError(Exception):
    """The settings file is malformed, so the run cannot know what to judge."""


def _pattern_regex(pattern):
    """Compile a path glob: `*` and `?` stay inside one segment, `**` crosses them, a final `/` takes a tree."""
    if pattern.endswith("/"):
        pattern += "**"
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def _exclusion(entry, position):
    if not isinstance(entry, dict) or set(entry) != {"path", "reason"}:
        raise ConfigError("exclude[%d]: expected exactly the keys \"path\" and \"reason\"" % position)
    path, reason = entry["path"], entry["reason"]
    if not isinstance(path, str) or not path or path.startswith(("/", "./", "../")):
        raise ConfigError("exclude[%d]: \"path\" must be a non-empty path relative to the repository root" % position)
    if not isinstance(reason, str) or not reason.strip():
        raise ConfigError("exclude[%d]: \"reason\" must say why %s is not judged" % (position, path))
    return path, reason, _pattern_regex(path)


def _extra(entry, position):
    where = "governance.extra[%d]" % position
    if not isinstance(entry, dict) or set(entry) != {"pattern", "reason"}:
        raise ConfigError("%s: expected exactly the keys \"pattern\" and \"reason\"" % where)
    pattern, reason = entry["pattern"], entry["reason"]
    if not isinstance(pattern, str) or not pattern:
        raise ConfigError("%s: \"pattern\" must be a non-empty regular expression" % where)
    if not isinstance(reason, str) or not reason.strip():
        raise ConfigError("%s: \"reason\" must say why %s is a governance reference" % (where, pattern))
    try:
        regex = re.compile(pattern)
    except re.error as error:
        raise ConfigError("%s: %r is not a valid regular expression: %s" % (where, pattern, error))
    if regex.search(""):
        raise ConfigError("%s: %r matches empty text, so it would name no reference" % (where, pattern))
    return governance.Extra(pattern, reason, regex)


def _governance(data):
    """The Matcher the settings ask for; the core is always part of it, so a setting can only add references."""
    if not isinstance(data, dict) or set(data) - {"packs", "extra"}:
        raise ConfigError("\"governance\" must be an object whose only keys are \"packs\" and \"extra\"")
    packs, extras = data.get("packs", []), data.get("extra", [])
    if not isinstance(packs, list) or not all(isinstance(name, str) for name in packs):
        raise ConfigError("\"governance.packs\" must be a list of pack names")
    unknown = [name for name in packs if name not in governance.PACKS]
    if unknown:
        raise ConfigError("unknown governance pack %r; the packs are %s"
                          % (unknown[0], ", ".join(sorted(governance.PACKS))))
    if not isinstance(extras, list):
        raise ConfigError("\"governance.extra\" must be a list")
    if not packs and not extras:
        return governance.DEFAULT
    return governance.matcher(tuple(dict.fromkeys(packs)),
                              tuple(_extra(entry, position) for position, entry in enumerate(extras)))


def parse(text):
    """Parse the settings file's text; raises ConfigError on anything but the documented shape."""
    try:
        data = json.loads(text)
    except ValueError as error:
        raise ConfigError("not valid JSON: %s" % error)
    if not isinstance(data, dict) or set(data) - {"exclude", "governance"}:
        raise ConfigError("expected one object whose only keys are \"exclude\" and \"governance\"")
    entries = data.get("exclude", [])
    if not isinstance(entries, list):
        raise ConfigError("\"exclude\" must be a list")
    return Config(tuple(_exclusion(entry, position) for position, entry in enumerate(entries)),
                  _governance(data.get("governance", {})))


def skipped_by_default(path):
    """True for a path under a directory, or with a file name, that no repository authors by hand."""
    parts = path.split("/")
    return parts[-1] in DEFAULT_SKIP_FILES or any(part in DEFAULT_SKIP_DIRS for part in parts[:-1])


def excluded(config, path):
    """True when the repository's settings exclude this root-relative path."""
    return any(regex.match(path) for _pattern, _reason, regex in config.exclusions)
