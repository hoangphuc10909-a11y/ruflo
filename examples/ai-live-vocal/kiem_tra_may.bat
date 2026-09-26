@echo off
REM Buoc 1: kiem tra may, tao bao cao (khong thay doi gi tren may).
cd /d "%~dp0"
if exist "AI LIVE VOCAL.exe" ( start "" /wait "AI LIVE VOCAL.exe" --kiem-tra & goto :eof )
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% run_app.py --kiem-tra
echo Bao cao: %APPDATA%\AILiveVocal\bao-cao-kiem-tra.txt
pause
