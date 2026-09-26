@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo A1 CLEAN Machine 2 - Reader reauthorization (official Google installed-app flow)
echo.

set "PY=C:\Users\feri-admin\.a1clean\runtime\python-3.11.9-embed-amd64\python.exe"
set "PIP=C:\Users\feri-admin\.a1clean\runtime\python-3.11.9-embed-amd64\pip.pyz"
set "SITE=C:\Users\feri-admin\.a1clean\runtime\python-3.11.9-embed-amd64\Lib\site-packages"

if not exist "%PY%" (
  echo Portable Python runtime is missing. Restoring the governed Machine 2 runtime...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Ensure-A1PortablePython311.ps1"
  if errorlevel 1 goto :runtimefail
)

"%PY%" -c "import google_auth_oauthlib, googleapiclient" >nul 2>&1
if errorlevel 1 (
  echo Installing Google OAuth helper library into the existing governed runtime once...
  if not exist "%PIP%" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Ensure-A1PortablePython311.ps1"
    if errorlevel 1 goto :runtimefail
  )
  "%PY%" "%PIP%" install --disable-pip-version-check --quiet --upgrade --target "%SITE%" "google-auth-oauthlib>=1.2,<2"
  if errorlevel 1 goto :pipfail
)

"%PY%" "%~dp0restore_a1_drive_reader_official.py"
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

:runtimefail
echo A1_READER_REAUTH_LAUNCHER=FAIL_PORTABLE_PYTHON_RUNTIME
pause
exit /b 21

:pipfail
echo A1_READER_REAUTH_LAUNCHER=FAIL_GOOGLE_OAUTH_LIBRARY_INSTALL
pause
exit /b 22
