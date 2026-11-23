@echo off
setlocal
title GOW3rehooked Xbox Prompts
echo Close GOW3rehooked before installing. Your game files and saves are kept.
echo.
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 (
    py -3 "%~dp0apply.py" %*
    goto finished
)
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 (
    python "%~dp0apply.py" %*
    goto finished
)
echo Python 3.10 or newer is required. Install Python 3 from https://www.python.org/downloads/
echo Include the Python launcher, then open this file again. No extra packages are needed.
:finished
echo.
pause
