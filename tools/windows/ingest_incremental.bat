@echo off
cd /d "%~dp0\..\.."
echo.
echo ============================================================
echo  CASForge - Incremental Ingest + Index Rebuild
echo  Repo path from .env: FEATURES_REPO_PATH
echo ============================================================
echo.
python tools/cli/ingest.py
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
