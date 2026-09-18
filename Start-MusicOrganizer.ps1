$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

function Stop-WithMessage([string]$message) {
    Write-Host "`n$message" -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit 1
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Stop-WithMessage 'Node.js was not found. Install Node.js 20 or newer.'
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Stop-WithMessage 'npm was not found. Check that Node.js is on PATH.'
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Stop-WithMessage 'Python was not found. Install Python 3.11 or newer.'
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'node_modules\electron'))) {
    Stop-WithMessage 'Node dependencies are missing. Run npm install in the project directory.'
}

$env:PYTHONPATH = Join-Path $projectRoot 'engine'
$mutagenCheck = & python -X utf8 -c 'import mutagen' 2>&1
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage 'Python Mutagen is missing. Run python -m pip install -e .\engine.'
}

Write-Host 'Starting Music Organizer...' -ForegroundColor Cyan
npm run dev
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nMusic Organizer failed to start. Exit code: $LASTEXITCODE" -ForegroundColor Red
    Read-Host 'Press Enter to exit'
}
