param([uri]$ServiceUrl = 'http://127.0.0.1:8767/')
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $head = git rev-parse HEAD
    if ($LASTEXITCODE) { throw '无法读取本地提交' }
    $proxy = git config --get-urlmatch http.proxy 'https://github.com/rabbittttt/Order_Analysis.git'
    $remoteHead = '未核实'
    if ($proxy) {
        $remote = git ls-remote github refs/heads/main
        if ($LASTEXITCODE -eq 0 -and $remote) { $remoteHead = ($remote -split '\s+')[0] }
    }
    $health = $null
    try {
        $health = Invoke-RestMethod -Uri ($ServiceUrl.AbsoluteUri.TrimEnd('/') + '/health') -TimeoutSec 4
        if ($health.application -ne 'order-dashboard') { $health = $null }
    } catch { }
    [pscustomobject]@{
        '本地提交' = $head
        '远端 main' = $remoteHead
        '访问地址' = $ServiceUrl.AbsoluteUri
        '访问端口' = $ServiceUrl.Port
        '服务监听端口' = if ($health.service_port) { $health.service_port } else { '未核实' }
        '运行提交' = if ($health.commit) { $health.commit } else { '未核实' }
        '运行指纹' = if ($health) { $health.service_fingerprint } else { '未核实' }
        '服务批次' = if ($health) { $health.dataset_id } else { '未核实' }
        '提交检查' = "https://github.com/rabbittttt/Order_Analysis/commit/$head/checks"
    } | Format-List
} finally { Pop-Location }
