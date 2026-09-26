@echo off
setlocal
cd /d "%~dp0"
echo A1 CLEAN Machine 2 - Reader reauthorization
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Restore-A1DriveReaderExisting.ps1"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo A1_READER_REAUTH_LAUNCHER=PASS
  echo Reader token refreshed. Machine 2 can return to automatic operation after guardrail verification.
) else (
  echo A1_READER_REAUTH_LAUNCHER=FAIL exit_code=%RC%
  echo Copy the error text shown above back to ChatGPT.
)
echo.
pause
exit /b %RC%
