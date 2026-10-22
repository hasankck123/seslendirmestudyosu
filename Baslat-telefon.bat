@echo off
setlocal
cd /d "%~dp0"
set "PY="
for %%I in (pythonw.exe) do set "PY=%%~$PATH:I"
if not defined PY for %%I in (python.exe) do set "PY=%%~$PATH:I"
if not defined PY (
    echo Python bulunamadi. Python 3.10 veya uzeri gerekir.
    pause
    exit /b 1
)
start "" /b "%PY%" "%~dp0serve.py" --host 0.0.0.0 --open-browser
exit /b
