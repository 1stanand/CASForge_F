@echo off
cd /d "%~dp0\..\.."
echo.
echo ============================================================
echo  CASForge - Interactive Retrieval Test
echo  Type queries at the prompt. Type :help for commands.
echo ============================================================
echo.
python tools/cli/test_retrieval.py
