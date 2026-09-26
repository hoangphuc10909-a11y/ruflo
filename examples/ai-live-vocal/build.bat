@echo off
REM Build AI LIVE VOCAL thanh file .exe (can Python 3.11 64-bit tu python.org, tick "Add to PATH").
cd /d "%~dp0"
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller==6.10.0 pytest || goto :err
python -m pytest -q tests || goto :err
pyinstaller --noconfirm --windowed --name "AI LIVE VOCAL" ^
  --add-data "cubase\ailive_vocalbridge.js;cubase" ^
  --collect-all soundcard --hidden-import rtmidi ^
  run_app.py || goto :err
echo.
echo XONG: dist\AI LIVE VOCAL\AI LIVE VOCAL.exe
pause
exit /b 0
:err
echo LOI khi build - xem thong bao phia tren.
pause
exit /b 1
