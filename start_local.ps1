param([ValidateRange(0,21600)][int]$LiveSeconds=0)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
# 建立本次安装需要的本地目录；SQLite 首次运行不要求预装 PostgreSQL。
New-Item -ItemType Directory -Force -Path 'data','logs' | Out-Null
if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
    & $projectPython native_database.py ensure
    if ($LASTEXITCODE -ne 0) { throw 'Database could not start. Configure DATABASE_URL or set up the project PostgreSQL runtime.' }
}
# 启动时恢复独立研究队列；工作者内部的排他锁防止重复进程重复执行。
& $projectPython -c "from core.task_manager import ensure_worker; ensure_worker()"
if ($LASTEXITCODE -ne 0) { throw 'Research task worker could not start.' }
# 检查指定本机端口是否已监听：用短连接判断，始终关闭客户端。这里只判端口占用，后续 API 健康检查再确认项目身份。
function Test-LocalPort([int]$port) {
    $client=[System.Net.Sockets.TcpClient]::new()
    try { $client.Connect('127.0.0.1',$port); return $true } catch { return $false } finally { $client.Dispose() }
}
if (-not (Test-LocalPort 8010)) {
    $apiProcess=Start-Process -FilePath $projectPython -ArgumentList '-m','uvicorn','service:app','--host','127.0.0.1','--port','8010' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput 'logs\api.stdout.log' -RedirectStandardError 'logs\api.stderr.log' -PassThru
    $apiProcess.Id | Set-Content -LiteralPath 'logs\api.pid'
}
if (-not (Test-LocalPort 8502)) {
    $marketProcess=Start-Process -FilePath $projectPython -ArgumentList '-m','streamlit','run','market_app.py','--server.address=127.0.0.1','--server.port=8502','--server.headless=true','--browser.gatherUsageStats=false','--server.fileWatcherType=none' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput 'logs\market.stdout.log' -RedirectStandardError 'logs\market.stderr.log' -PassThru
    $marketProcess.Id | Set-Content -LiteralPath 'logs\market.pid'
}
if ($LiveSeconds -gt 0) {
    $liveProcess=Start-Process -FilePath $projectPython -ArgumentList 'worker.py','--seconds',"$LiveSeconds" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput 'logs\worker.stdout.log' -RedirectStandardError 'logs\worker.stderr.log' -PassThru
    $liveProcess.Id | Set-Content -LiteralPath 'logs\worker.pid'
}
$apiReady=$false
for ($attempt=0; $attempt -lt 10; $attempt++) {
    try {
        $health=Invoke-RestMethod 'http://127.0.0.1:8010/health' -TimeoutSec 6
        if ($health.api -eq 'ok' -and $health.execution_mode -eq 'paper' -and $health.database -eq 'connected') { $apiReady=$true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (-not $apiReady) { throw 'Project API health check failed on port 8010. Inspect logs or port ownership; existing listeners were not terminated.' }
Write-Output 'Verified project API/database. Dashboard: http://127.0.0.1:8502 ; API: http://127.0.0.1:8010/docs'
