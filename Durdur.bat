@echo off
setlocal
cd /d "%~dp0"
set "PY="
for %%I in (python.exe) do set "PY=%%~$PATH:I"
if not defined PY (
    echo Python bulunamadi.
    pause
    exit /b 1
)
"%PY%" "%~dp0serve.py" --stop
timeout /t 2 >nul
exit /b
