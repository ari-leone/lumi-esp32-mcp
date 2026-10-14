param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'start.ps1') -NoBrowser
$bridgeDir = Join-Path (Split-Path $PSScriptRoot) 'xiaozhi_openai_bridge'
$voiceConfig = Get-Content -LiteralPath (Join-Path $bridgeDir 'local_config.json') -Raw | ConvertFrom-Json
$voiceUrl = "http://$($voiceConfig.pc_ip):$($voiceConfig.port)"
$localAddresses = @(Get-NetIPAddress -AddressFamily IPv4 | Select-Object -ExpandProperty IPAddress)
if ($voiceConfig.pc_ip -notin $localAddresses) {
    throw 'La IP del PC cambió. Hay que actualizar la dirección del puente y de la placa antes de usar la voz. El bloc del PC sigue disponible.'
}
$voiceRunning = $false
try {
    $health = Invoke-RestMethod "$voiceUrl/health" -TimeoutSec 2
    if ($health.notebook_provider -eq 'pc_mcp' -and $health.pc_mcp_ready) { $voiceRunning = $true }
    else { throw 'Hay un puente activo con otra configuración o MCP no está listo. Comprueba el puente antes de lanzar otro.' }
} catch {
    if ($_.Exception.Message -like 'Hay un puente activo*') { throw }
}
if (-not $voiceRunning) {
    $voicePython = Join-Path (Split-Path $PSScriptRoot) '.deps\xiaozhi-bridge-venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $voicePython)) { throw 'No se encuentra el entorno Python del puente.' }
    $logDir = Join-Path $env:LOCALAPPDATA 'LumiNotes\logs'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $voiceArgs = @('-m','uvicorn','server:app','--host',$voiceConfig.pc_ip,'--port',"$($voiceConfig.port)",'--no-access-log')
    $voiceProcess = Start-Process -FilePath $voicePython -ArgumentList $voiceArgs -WorkingDirectory $bridgeDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'bridge.stdout.log') -RedirectStandardError (Join-Path $logDir 'bridge.stderr.log') -PassThru
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        Start-Sleep -Milliseconds 500
        if ($voiceProcess.HasExited) { throw 'El puente no ha podido arrancar. Revisa el registro de LumiNotes\logs.' }
        try {
            $health = Invoke-RestMethod "$voiceUrl/health" -TimeoutSec 1
            if ($health.notebook_provider -eq 'pc_mcp' -and $health.pc_mcp_ready) { $voiceRunning = $true; break }
        } catch {}
    }
    Set-Content -LiteralPath (Join-Path $env:LOCALAPPDATA 'LumiNotes\bridge.pid') -Value $voiceProcess.Id
    if (-not $voiceRunning) { throw 'El puente arrancó, pero no se ha verificado la conexión MCP. Revisa el registro.' }
}
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8765' }
Write-Host 'Lumi: aplicación y puente MCP preparados. Toca la placa para conversar.'
