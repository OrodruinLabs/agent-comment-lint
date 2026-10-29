#!/bin/sh
# Runs the hook for the agent named in $1, and turns every failure into exit 2, the code that blocks a write.
if ! command -v agent-comment-lint >/dev/null 2>&1; then
  echo "Blocked: agent-comment-lint is not installed." >&2
  exit 2
fi
agent-comment-lint --hook --agent "$1"
code=$?
[ "$code" -eq 0 ] && exit 0
# Codex lets a patch through on exit 2 with nothing on stderr, so a failure that printed nothing still gives a reason.
[ "$code" -eq 2 ] || echo "Blocked: agent-comment-lint failed with exit code $code." >&2
exit 2
