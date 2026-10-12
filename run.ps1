param([ValidateSet('serve','market','api','worker','test','preflight')][string]$Action='market')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Create the project .venv first; see README.md.' }
if ($Action -in @('market','api','worker') -and (Test-Path -LiteralPath '.runtime\database.json')) {
    & $projectPython native_database.py ensure
    if ($LASTEXITCODE -ne 0) { throw 'Project database startup failed; inspect logs/postgres.log.' }
}
switch ($Action) {
    'market' { & $projectPython -m streamlit run market_app.py --server.address 127.0.0.1 --server.port 8502 --server.headless true --server.fileWatcherType none }
    'api' { & $projectPython -m uvicorn service:app --host 127.0.0.1 --port 8010 }
    'worker' { & $projectPython worker.py --seconds 90 }
    'serve' { & $projectPython -m streamlit run app.py --server.address 127.0.0.1 --server.headless true }
    'test' { & $projectPython -m pytest -q }
    'preflight' { & $projectPython collect.py --preflight }
}
exit $LASTEXITCODE
