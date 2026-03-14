@echo off
cd /d "%~dp0\..\.."
echo.
echo ============================================================
echo  CASForge - Full Rebuild
echo  (drops all data, re-parses everything from FEATURES_REPO_PATH in .env)
echo ============================================================
echo.
echo WARNING: This will delete all parsed data and re-parse from scratch.
set /p confirm=Are you sure? (y/n):
if /i not "%confirm%"=="y" (
    echo Cancelled.
    pause
    exit /b 0
)

echo.
python tools/cli/ingest.py --full-rebuild
if errorlevel 1 goto error

echo.
echo Rebuilding vector index...
python tools/cli/build_index.py
if errorlevel 1 goto error

echo.
echo Done.
pause
exit /b 0

:error
echo.
echo [FAILED] See error above.
pause
exit /b 1
