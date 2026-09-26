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

"%PY%" -c "import google_auth_oauthlib, googleapiclient.discovery, google.api_core.client_options" >nul 2>&1
if errorlevel 1 (
  echo Installing complete Google OAuth and Drive API dependency set into the existing governed runtime once...
  if not exist "%PIP%" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Ensure-A1PortablePython311.ps1"
    if errorlevel 1 goto :runtimefail
  )
  "%PY%" "%PIP%" install --disable-pip-version-check --quiet --upgrade --target "%SITE%" "google-auth>=2.40,<3" "google-auth-oauthlib>=1.2,<2" "google-api-core>=2,<3" "google-api-python-client>=2,<3" "google-auth-httplib2>=0.2,<1" "httplib2>=0.22,<1" "uritemplate>=4,<5"
  if errorlevel 1 goto :pipfail
)

"%PY%" -c "import google_auth_oauthlib, googleapiclient.discovery, google.api_core.client_options" >nul 2>&1
if errorlevel 1 goto :importfail

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

:importfail
echo A1_READER_REAUTH_LAUNCHER=FAIL_GOOGLE_DEPENDENCY_IMPORT
echo Required Google OAuth or Drive API modules are still unavailable after repair.
pause
exit /b 23
