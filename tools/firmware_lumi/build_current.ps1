param([string]$SourceDir = (Join-Path $env:TEMP 'lumi-fw-20261004\xiaozhi-esp32-2.4.2'))
$ErrorActionPreference = 'Stop'
$lumiBuildRoot = Split-Path (Split-Path $PSScriptRoot)
$lumiBuildPython = Join-Path $lumiBuildRoot '.deps\idf-tools\python_env\idf6.0_py3.12_env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $lumiBuildPython)) { throw 'No se encuentra el entorno ESP-IDF Python 3.12.' }
if (-not (Test-Path -LiteralPath (Join-Path $SourceDir 'CMakeLists.txt'))) { throw 'No se encuentra la fuente de firmware indicada.' }
$env:IDF_TOOLS_PATH = Join-Path $lumiBuildRoot '.deps\idf-tools'
$env:PATH = (Split-Path $lumiBuildPython) + ';' + $env:PATH
. (Join-Path $lumiBuildRoot '.deps\esp-idf-v6.0.2\export.ps1')
if (-not $env:IDF_PATH) { throw 'No se ha activado ESP-IDF.' }
$env:IDF_COMPONENT_MANAGER = '1'
$env:IDF_COMPONENT_CHECK_NEW_VERSION = '0'
$env:IDF_COMPONENT_API_TIMEOUT = '5'
& $lumiBuildPython (Join-Path $env:IDF_PATH 'tools\idf.py') -C $SourceDir -D CMAKE_NINJA_FORCE_RESPONSE_FILE=ON build
if ($LASTEXITCODE -ne 0) { throw 'No se ha completado la compilación. No grabar ningún binario.' }
& $lumiBuildPython (Join-Path $PSScriptRoot 'verify_pc_mcp_build.py') (Join-Path $SourceDir 'build')
if ($LASTEXITCODE -ne 0) { throw 'La verificación del firmware no ha pasado.' }
Write-Host 'Compilación verificada. No se ha grabado ni borrado la placa.'
