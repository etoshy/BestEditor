$ErrorActionPreference = 'Stop'
Write-Host '=== PYTHON UNIT TESTS ===' -ForegroundColor Cyan
python -m unittest discover -s tests -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host '=== JAVASCRIPT SYNTAX ===' -ForegroundColor Cyan
node --check static/app.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
node --check static/ideias.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
node --check static/ordenacao.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
node --check static/metodo.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
node --check static/metodo_ui.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
node --check static/canal.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
node --check static/canal_ui.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
node --check static/ytapi.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
node --check static/ytapi_ui.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host '=== TESTES OK ===' -ForegroundColor Green
