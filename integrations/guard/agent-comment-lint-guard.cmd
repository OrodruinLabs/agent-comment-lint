@echo off
rem Runs the hook for the agent named in %1, and turns every failure into exit 2, the code that blocks a write.
where agent-comment-lint >nul 2>&1
if errorlevel 1 (
  echo Blocked: agent-comment-lint is not installed.>&2
  exit /b 2
)
call agent-comment-lint --hook --agent %1
if errorlevel 1 exit /b 2
exit /b 0
