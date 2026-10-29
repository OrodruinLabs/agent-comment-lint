#!/bin/sh
# Runs the hook for the agent named in $1, and turns every failure into exit 2, the code that blocks a write.
if ! command -v agent-comment-lint >/dev/null 2>&1; then
  echo "Blocked: agent-comment-lint is not installed." >&2
  exit 2
fi
agent-comment-lint --hook --agent "$1" && exit 0
exit 2
