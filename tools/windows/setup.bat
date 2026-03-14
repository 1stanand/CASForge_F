@echo off
cd /d "%~dp0\..\.."
echo.
echo ============================================================
echo  CASForge - Setup
echo  (DB + schema + ingest + index all from .env)
echo ============================================================
echo.
python setup.py
pause
