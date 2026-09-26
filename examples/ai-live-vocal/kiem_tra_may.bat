@echo off
REM Buoc 1: kiem tra may, tao bao cao (khong thay doi gi tren may).
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -m ailive.diagnose
pause
