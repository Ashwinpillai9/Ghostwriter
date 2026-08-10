@echo off
REM Launches Ghostwriter from cmd.exe. Works from any drive or directory.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m ghostwriter.app %*
