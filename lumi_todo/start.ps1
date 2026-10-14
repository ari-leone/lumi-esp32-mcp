param([int]$Port = 8765, [string]$DataDir, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$candidates = @(
    "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
    (Join-Path (Split-Path $projectDir) '.deps\xiaozhi-bridge-venv\Scripts\python.exe')
)
$pythonPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonPath) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) { $pythonPath = $pythonCommand.Source }
}
if (-not $pythonPath) { throw 'No se encuentra Python. Instala Python 3.11 o posterior.' }
if (-not $DataDir) { $DataDir = Join-Path $env:LOCALAPPDATA 'LumiNotes' }
$url = "http://127.0.0.1:$Port"
$isRunning = $false
try {
    $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 2
    if ($health.app -eq 'lumi-todo') { $isRunning = $true }
    else { throw 'El puerto está ocupado por otra aplicación.' }
} catch {
    if ($_.Exception.Message -eq 'El puerto está ocupado por otra aplicación.') { throw }
}
if (-not $isRunning) {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
    $arguments = @('"' + (Join-Path $projectDir 'server.py') + '"', '--port', "$Port", '--data-dir', '"' + $DataDir + '"')
    $process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 200
        if ($process.HasExited) { throw 'Lumi no ha podido arrancar. Comprueba el puerto y los permisos de la carpeta de datos.' }
        try { $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 1; if ($health.app -eq 'lumi-todo') { $isRunning = $true; break } } catch {}
    }
    if (-not $isRunning) { throw 'No se ha podido verificar el arranque de Lumi.' }
    Set-Content -LiteralPath (Join-Path $DataDir 'server.pid') -Value $process.Id
}
if (-not $NoBrowser) { Start-Process $url }
Write-Host "Lumi disponible en $url"
