@echo off
rem Runs the hook for the agent named in %1, and turns every failure into exit 2, the code that blocks a write.
setlocal
set "ACL_COMMAND="
rem The command is looked up on PATH only, so a file dropped in the working directory cannot stand in for it.
for %%I in (agent-comment-lint.exe agent-comment-lint.cmd) do if not defined ACL_COMMAND set "ACL_COMMAND=%%~$PATH:I"
if not defined ACL_COMMAND (
  echo Blocked: agent-comment-lint is not installed.>&2
  exit /b 2
)
call "%ACL_COMMAND%" --hook --agent %1
set "ACL_CODE=%errorlevel%"
rem Negative exit codes, such as a crash, are failures too, which "if errorlevel 1" would miss.
if "%ACL_CODE%"=="0" exit /b 0
rem Codex lets a patch through on exit 2 with nothing on stderr, so a failure that printed nothing still gives a reason.
if not "%ACL_CODE%"=="2" echo Blocked: agent-comment-lint failed with exit code %ACL_CODE%.>&2
exit /b 2
