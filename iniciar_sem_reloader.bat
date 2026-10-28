@echo off
rem v84_259: abre o site SEM o reinicio automatico (pra lotes longos da geracao rapida).
rem Mudou um arquivo .py? Feche esta janela e abra de novo.
set SEM_RELOADER=1
python app.py
pause
