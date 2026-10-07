@echo off
cd /d "%~dp0"
python -m morningpaper open
if errorlevel 1 (
  echo Skills Morning Brief requires Python 3.11 or newer. See README.md.
  pause
)
