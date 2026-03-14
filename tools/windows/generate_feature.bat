@echo off
cd /d "%~dp0\..\.."
echo.
echo ============================================================
echo  CASForge - Generate Feature File from JIRA Story
echo  Usage: pass args after this script name
echo  Example: generate_feature.bat --csv workspace\samples\sampleJira\HD_BANK_EPIC.csv --story CAS-256008 --intents-only
echo  Example: generate_feature.bat --csv workspace\samples\sampleJira\HD_BANK_EPIC.csv --story CAS-256008 --flow-type unordered
echo  Example: generate_feature.bat --csv workspace\samples\sampleJira\HD_BANK_EPIC.csv --all --flow-type ordered
echo ============================================================
echo.
python tools/cli/generate_feature.py %*
pause
