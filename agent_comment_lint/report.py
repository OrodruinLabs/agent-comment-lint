"""Rendering a run as text or JSON. Ordering is fixed so two runs over the same tree print the same bytes."""
import json
from collections import namedtuple

Report = namedtuple("Report", ["mode", "scanned", "findings", "errors", "unresolved_lines"])
Report.__doc__ = ("A finished run: `findings` are (path, Finding), `errors` are (path, line or None, message), "
                  "`scanned` counts the files judged.")

FORMAT_VERSION = 1

HOOK_SCOPE = "Only the lines this write adds or changes are judged; comments elsewhere in the file are fine.\n"
FIXES = {
    "C1": "Keep one line that says why the code is this way; put the rest in the commit message or the PR description.",
    "C3": "Remove the reference; say what the code needs, not where the decision was recorded.",
    "C5": "Shorten the assertion message to at most two lines.",
    "C7": "Shorten the comment, or move it onto its own line above the code.",
}
EXCERPT_LINES = 6
EXCERPT_WIDTH = 120
HOOK_CLOSING = (
    "Fix the comment and retry the same tool call.",
    "Splitting the comment across blank lines, or writing the file another way (Bash, a script, another tool), "
    "does not satisfy the policy.",
    "Adding an exclusion to .agent-comment-lint.json is not the fix: exclusions are for generated and "
    "third-party code, and a new one has no effect here until a human commits it.",
)
WRITE_RETRY = "Re-send this Write with only the comment lines changed."


def exit_code(report):
    """0 clean, 1 violations, 2 when anything could not be scanned."""
    if report.errors:
        return 2
    return 1 if report.findings else 0


def _sorted_findings(report):
    return sorted(report.findings, key=lambda item: (item[0], item[1].line, item[1].rule, item[1].message))


def _sorted_errors(report):
    return sorted(report.errors, key=lambda item: (item[0], item[1] or 0, item[2]))


def _error_line(path, line, message):
    where = path if line is None else "%s:%d" % (path, line)
    return "%s: could not scan: %s" % (where, message)


def _finding_line(path, finding):
    return "%s:%d: %s: %s" % (path, finding.line, finding.rule, finding.message)


def _summary(report):
    """(summary lines for stdout, error lines for stderr): the part of the text that follows the findings."""
    out = []
    err = [_error_line(*error) for error in _sorted_errors(report)]
    if report.errors:
        err.append("agent-comment-lint: no verdict, %d problem(s) stopped the scan." % len(report.errors))
    elif report.findings:
        files = len({path for path, _finding in report.findings})
        out.append("agent-comment-lint: %d violation(s) in %d of %d file(s) scanned."
                   % (len(report.findings), files, report.scanned))
    else:
        out.append("agent-comment-lint: clean, %d file(s) scanned." % report.scanned)
    return out, err


def as_text(report):
    """(stdout, stderr) text: one `path:line: rule: message` per finding, then a one-line summary."""
    out = [_finding_line(path, finding) for path, finding in _sorted_findings(report)]
    summary, err = _summary(report)
    return "".join(line + "\n" for line in out + summary), "".join(line + "\n" for line in err)


def _excerpt(source, finding):
    """The finding's source lines, indented, cut to the excerpt limits; empty when the lines are not known."""
    if source is None:
        return []
    lines = source[finding.line - 1:finding.end_line]
    shown = ["    " + (line if len(line) <= EXCERPT_WIDTH else line[:EXCERPT_WIDTH - 1] + "\u2026")
             for line in lines[:EXCERPT_LINES]]
    if len(lines) > EXCERPT_LINES:
        shown.append("    \u2026 %d more line(s)" % (len(lines) - EXCERPT_LINES))
    return shown


def hook_text(report, texts, header, closing):
    """Hook stderr: `header` ends in a newline; `closing` lines have none and appear only with findings."""
    lines = []
    split = {}
    for path, finding in _sorted_findings(report):
        if path not in split:
            split[path] = texts[path].splitlines() if path in texts else None
        lines.append(_finding_line(path, finding))
        lines.extend(_excerpt(split[path], finding))
        if finding.rule in FIXES:
            lines.append("  Fix: " + FIXES[finding.rule])
    out, err = _summary(report)
    lines.extend(out + err)
    if report.findings:
        lines.extend(closing)
    return header + "".join(line + "\n" for line in lines)


def as_json(report):
    """The run as one JSON document with sorted keys."""
    counts = {}
    for _path, finding in report.findings:
        counts[finding.rule] = counts.get(finding.rule, 0) + 1
    document = {
        "version": FORMAT_VERSION,
        "mode": report.mode,
        "exit_code": exit_code(report),
        "files_scanned": report.scanned,
        "unresolved_lines": report.unresolved_lines,
        "counts": counts,
        "findings": [{"path": path, "line": finding.line, "end_line": finding.end_line,
                      "rule": finding.rule, "message": finding.message}
                     for path, finding in _sorted_findings(report)],
        "errors": [{"path": path, "line": line, "message": message}
                   for path, line, message in _sorted_errors(report)],
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"
