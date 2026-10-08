@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe scripts\fetch_assets.py
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe run.py
