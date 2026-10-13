@echo off
cd /d "%~dp0"
if exist ".venv" call .venv\Scripts\activate
echo Feche o app (janela do app.py) antes de testar.
python testar.py %*
pause
