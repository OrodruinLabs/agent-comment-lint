@echo off
rem Appends one hook event to the file named by AGENT_COMMENT_LINT_CAPTURE; capture never blocks the agent.
if "%AGENT_COMMENT_LINT_CAPTURE%"=="" (
  echo AGENT_COMMENT_LINT_CAPTURE is not set, so this event was not captured.>&2
  exit /b 0
)
findstr "^" >> "%AGENT_COMMENT_LINT_CAPTURE%"
exit /b 0
