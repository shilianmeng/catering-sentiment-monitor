# 一键启动：后端 8091 + 前端 5180。面试演示时双击运行即可。
#   .\start.ps1            正常启动
#   .\start.ps1 -Reset     先重置演示库（舆情演示表删表重建 + 灌种子 + 回到 T0），再启动。
#                          官方处罚记录和原文快照不删：重置前自动整表备份到 backend\data\backups\，
#                          重置后逐条核对，有丢失或改动就报错停下，不会继续启动。
#   .\start.ps1 -NoFrontend 只起后端（前端用 npm run dev 单独跑）
param(
    [switch]$Reset,
    [switch]$NoFrontend
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$health = 'http://127.0.0.1:8091/health'

function Fail($msg) { Write-Host "[启动失败] $msg" -ForegroundColor Red; exit 1 }

Write-Host '==> 检查环境' -ForegroundColor Cyan
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Fail '找不到 python，请先安装 Python 3.11+' }
python -c "import fastapi, uvicorn, pymysql, fpdf" 2>$null
if ($LASTEXITCODE -ne 0) { Fail '依赖没装全，先执行：cd backend; python -m pip install -r requirements.txt' }

$mysqlUp = Test-NetConnection -ComputerName 127.0.0.1 -Port 3306 -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $mysqlUp) {
    Fail 'MySQL 3306 没在监听。请先启动 MySQL80 服务（services.msc），或用 docker compose up -d mysql'
}
if (-not (Test-Path (Join-Path $backend '.env'))) {
    Write-Host '提示：没有 backend/.env，按默认值连接本机 MySQL(root/root)、不调用大模型。' -ForegroundColor Yellow
    Write-Host '      需要改连接串或配大模型 key 时：Copy-Item backend\.env.example backend\.env' -ForegroundColor Yellow
}

if ($Reset) {
    Write-Host '==> 重置演示库' -ForegroundColor Cyan
    Push-Location $backend
    python -m app.engine.demo --reset
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Fail '重置演示库失败，看上面的报错' }
}

Write-Host '==> 启动后端（新窗口）' -ForegroundColor Cyan
Start-Process -FilePath 'python' -ArgumentList 'run.py' -WorkingDirectory $backend -WindowStyle Normal

Write-Host '==> 等待后端就绪' -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $r = Invoke-RestMethod -Uri $health -TimeoutSec 2
        if ($r.status -eq 'ok') { $ready = $true; break }
    } catch { }
}
if (-not $ready) { Fail "后端 20 秒内没起来，看后端窗口的报错（常见：MySQL 密码不对）" }

if (-not $NoFrontend) {
    if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
        Write-Host '==> 首次运行，安装前端依赖（约 1-2 分钟）' -ForegroundColor Cyan
        Push-Location $frontend
        npm install
        $code = $LASTEXITCODE
        Pop-Location
        if ($code -ne 0) { Fail 'npm install 失败，检查 Node 版本（需要 20+）' }
    }
    Write-Host '==> 启动前端（新窗口）' -ForegroundColor Cyan
    Start-Process -FilePath 'npm.cmd' -ArgumentList 'run', 'dev' -WorkingDirectory $frontend -WindowStyle Normal
}

Write-Host ''
Write-Host '就绪：' -ForegroundColor Green
Write-Host '  页面     http://127.0.0.1:5180'
Write-Host '  接口文档 http://127.0.0.1:8091/docs'
Write-Host '  演示账号 analyst / pr / admin，密码都是 123456'
Write-Host '  关闭服务：.\stop.ps1'
