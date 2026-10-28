"""Rendering a run as text or JSON. Ordering is fixed so two runs over the same tree print the same bytes."""
import json
from collections import namedtuple

Report = namedtuple("Report", ["mode", "scanned", "findings", "errors", "unresolved_lines"])
Report.__doc__ = ("A finished run: `findings` are (path, Finding), `errors` are (path, line or None, message), "
                  "`scanned` counts the files judged.")

FORMAT_VERSION = 1


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


def as_text(report):
    """(stdout, stderr) text: one `path:line: rule: message` per finding, then a one-line summary."""
    out = ["%s:%d: %s: %s" % (path, finding.line, finding.rule, finding.message)
           for path, finding in _sorted_findings(report)]
    err = [_error_line(*error) for error in _sorted_errors(report)]
    if report.errors:
        err.append("agent-comment-lint: no verdict, %d problem(s) stopped the scan." % len(report.errors))
    elif report.findings:
        files = len({path for path, _finding in report.findings})
        out.append("agent-comment-lint: %d violation(s) in %d of %d file(s) scanned."
                   % (len(report.findings), files, report.scanned))
    else:
        out.append("agent-comment-lint: clean, %d file(s) scanned." % report.scanned)
    return "".join(line + "\n" for line in out), "".join(line + "\n" for line in err)


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
