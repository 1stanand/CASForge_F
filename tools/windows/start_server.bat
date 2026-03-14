@echo off
cd /d "%~dp0\..\.."
echo.
echo ============================================================
echo  CASForge - Web Server
echo  Open http://localhost:8000 in your browser
echo  Press Ctrl+C to stop
echo ============================================================
echo.
uvicorn casforge.web.app:app --host 0.0.0.0 --port 8000 --reload
