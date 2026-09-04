@echo off
cd /d "%~dp0"
python launcher.py --with-llm
if errorlevel 1 pause
