$ErrorActionPreference = 'Stop'
$bridgePython = Join-Path $PSScriptRoot '..\.deps\xiaozhi-bridge-venv\Scripts\python.exe'
Set-Location $PSScriptRoot
$bridgeConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'local_config.json') -Raw | ConvertFrom-Json
$bridgeAddress = $bridgeConfig.pc_ip
if (-not $bridgeAddress) { throw 'Falta pc_ip en local_config.json.' }
& $bridgePython -m uvicorn server:app --host $bridgeAddress --port 8002 --no-access-log
