#!/bin/sh
# Appends one hook event to the file named by AGENT_COMMENT_LINT_CAPTURE; capture never blocks the agent.
if [ -z "$AGENT_COMMENT_LINT_CAPTURE" ]; then
  echo "AGENT_COMMENT_LINT_CAPTURE is not set, so this event was not captured." >&2
  exit 0
fi
cat >> "$AGENT_COMMENT_LINT_CAPTURE"
echo >> "$AGENT_COMMENT_LINT_CAPTURE"
exit 0
