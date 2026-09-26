@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo A1 CLEAN Machine 2 - Reader reauthorization (official Google installed-app flow)
echo.

set "VENV=%USERPROFILE%\.a1clean\reader-oauth-helper-venv"
set "PY=%VENV%\Scripts\python.exe"

if not exist "%PY%" (
  echo Preparing isolated OAuth helper environment once...
  py -3 -m venv "%VENV%" >nul 2>&1
  if errorlevel 1 python -m venv "%VENV%"
  if errorlevel 1 goto :venvfail
)

"%PY%" -c "import google_auth_oauthlib, googleapiclient" >nul 2>&1
if errorlevel 1 (
  echo Installing Google OAuth helper libraries once...
  "%PY%" -m pip install --disable-pip-version-check --quiet "google-auth-oauthlib>=1.2,<2" "google-api-python-client>=2,<3"
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

:venvfail
echo A1_READER_REAUTH_LAUNCHER=FAIL_PYTHON_VENV
echo Python could not create the isolated OAuth helper environment.
pause
exit /b 21

:pipfail
echo A1_READER_REAUTH_LAUNCHER=FAIL_GOOGLE_OAUTH_LIBRARY_INSTALL
echo Google OAuth helper libraries could not be installed.
pause
exit /b 22
