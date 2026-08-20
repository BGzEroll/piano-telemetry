$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$PythonExe = 'C:\software\miniconda3\miniconda3\envs\piano-midi\python.exe'

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "piano-midi Python not found: $PythonExe"
}

& $PythonExe -m PyInstaller --noconfirm --clean "$ProjectRoot\PianoTelemetry.spec"

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

Write-Host "Built: $ProjectRoot\dist\PianoTelemetry.exe"
