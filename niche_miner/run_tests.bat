@echo off
python -m unittest discover -s tests -p "test_*.py" -v
if errorlevel 1 exit /b 1
node --check static\app.js
if errorlevel 1 exit /b 1
node --check static\ideias.js
if errorlevel 1 exit /b 1
node --check static\ordenacao.js
if errorlevel 1 exit /b 1
node --check static\metodo.js
if errorlevel 1 exit /b 1
node --check static\metodo_ui.js
if errorlevel 1 exit /b 1
node --check static\canal.js
if errorlevel 1 exit /b 1
node --check static\canal_ui.js
if errorlevel 1 exit /b 1
node --check static\ytapi.js
if errorlevel 1 exit /b 1
node --check static\ytapi_ui.js
if errorlevel 1 exit /b 1
echo TESTES OK
