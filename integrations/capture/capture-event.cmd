@echo off
rem Appends one hook event to the file named by AGENT_COMMENT_LINT_CAPTURE; capture never blocks the agent.
if "%AGENT_COMMENT_LINT_CAPTURE%"=="" (
  echo AGENT_COMMENT_LINT_CAPTURE is not set, so this event was not captured.>&2
  exit /b 0
)
rem PowerShell copies the bytes exactly; findstr breaks on the long single line an event usually is.
powershell -NoProfile -NonInteractive -Command "$i=[Console]::OpenStandardInput(); $o=[IO.File]::Open($env:AGENT_COMMENT_LINT_CAPTURE,'Append'); $i.CopyTo($o); $o.WriteByte(10); $o.Close()"
exit /b 0
