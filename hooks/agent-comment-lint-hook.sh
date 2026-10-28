#!/bin/sh
# Claude Code lets a write through on any exit but 2, so every way this wrapper can fail ends in exit 2.
here=$(cd "$(dirname "$0")" && pwd) || { echo "Blocked: the agent-comment-lint hook cannot find itself." >&2; exit 2; }
if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
  cd "$CLAUDE_PROJECT_DIR" || { echo "Blocked: cannot enter $CLAUDE_PROJECT_DIR." >&2; exit 2; }
fi
python=${AGENT_COMMENT_LINT_PYTHON:-python3}
command -v "$python" >/dev/null 2>&1 || { echo "Blocked: agent-comment-lint needs $python on PATH." >&2; exit 2; }
"$python" "$here/../check-agent-comment-lint.py" --hook
code=$?
[ "$code" -eq 0 ] && exit 0
exit 2
