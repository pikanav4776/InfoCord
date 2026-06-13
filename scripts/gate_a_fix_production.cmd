@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0\.."

echo ============================================================
echo Gate A - Fix production database (Option B: migrate Render DB)
echo ============================================================
echo.
echo Production is still on ep-falling-queen at revision edc83421847f.
echo You migrated ep-old-resonance separately - Render does NOT use that DB.
echo.
echo FASTEST: Render -^> Environment -^> DATABASE_URL = ep-old-resonance URL -^> Save
echo.
echo This script migrates whatever DATABASE_URL Render uses (Option B).
echo.

set "URLFILE=%~dp0..\.gate_a_database_url"
if exist "%URLFILE%" (
  echo Found .gate_a_database_url - using that file.
  set /p DATABASE_URL=<"%URLFILE%"
  goto :run
)

echo Paste DATABASE_URL from Render -^> infocord -^> Environment -^> DATABASE_URL
echo Copy the FULL one-line string with the eye icon. No line breaks.
echo.
set /p DATABASE_URL=DATABASE_URL: 

:run
if "%DATABASE_URL%"=="" (
  echo ERROR: DATABASE_URL is empty.
  exit /b 1
)

set FLASK_APP=run:app
call .venv\Scripts\activate.bat 2>nul

echo.
echo Target: %DATABASE_URL:~0,30%...
echo.

python scripts\gate_a_migrate.py
if errorlevel 1 exit /b 1

echo.
python scripts\gate_a_verify.py --insecure
exit /b %ERRORLEVEL%
