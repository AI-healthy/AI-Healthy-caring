param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $root "services/api")
try {
    $venvPython = Join-Path (Get-Location).Path ".venv/Scripts/python.exe"
    if (-not (Test-Path $venvPython)) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 -m venv .venv
        } else {
            & python -m venv .venv
        }
        if ($LASTEXITCODE -ne 0) { throw "Python virtual environment creation failed." }
    }
    & $venvPython -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ required'"
    if ($LASTEXITCODE -ne 0) { throw "Use Python 3.11 or newer." }
    & $venvPython -m pip install -e ".[dev,mcp]"
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    & $venvPython -m shiyi_api.local_runtime --port $Port
    if ($LASTEXITCODE -ne 0) { throw "Local runtime exited with code $LASTEXITCODE." }
} finally {
    Pop-Location
}
