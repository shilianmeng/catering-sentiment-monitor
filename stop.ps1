# 关闭本项目占用的 8091（后端）和 5180（前端）端口进程；不动其它端口。
$ErrorActionPreference = 'Continue'

foreach ($port in 8091, 5180) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { Write-Host "端口 $port 没有进程在监听" -ForegroundColor DarkGray; continue }
    foreach ($procId in ($conns | Select-Object -ExpandProperty OwningProcess -Unique)) {
        $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($p) {
            Write-Host "停止 $($p.ProcessName) (PID $procId)，端口 $port" -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}
Write-Host '已停止。' -ForegroundColor Green
