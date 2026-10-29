#!/bin/sh
# Claude Code lets a write through on any exit but 2, so every way this wrapper can fail ends in exit 2.
here=$(cd "$(dirname "$0")" && pwd) || { echo "Blocked: the agent-comment-lint hook cannot find itself." >&2; exit 2; }
if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
  cd "$CLAUDE_PROJECT_DIR" || { echo "Blocked: cannot enter $CLAUDE_PROJECT_DIR." >&2; exit 2; }
fi
usable() { "$@" -c 'import sys; sys.exit(sys.version_info < (3, 9))' </dev/null >/dev/null 2>&1; }
if [ -n "${AGENT_COMMENT_LINT_PYTHON:-}" ]; then
  usable "$AGENT_COMMENT_LINT_PYTHON" && set -- "$AGENT_COMMENT_LINT_PYTHON" || set --
elif usable python3; then set -- python3
elif usable python; then set -- python
elif usable py -3; then set -- py -3
else set --
fi
if [ "$#" -eq 0 ] && [ -n "${AGENT_COMMENT_LINT_PYTHON:-}" ]; then
  echo "Blocked: agent-comment-lint needs Python 3.9 or newer; AGENT_COMMENT_LINT_PYTHON=$AGENT_COMMENT_LINT_PYTHON is not." >&2
  exit 2
fi
[ "$#" -gt 0 ] || { echo "Blocked: agent-comment-lint needs Python 3.9 or newer on PATH." >&2; exit 2; }
"$@" "$here/../check-agent-comment-lint.py" --hook
code=$?
[ "$code" -eq 0 ] && exit 0
exit 2
