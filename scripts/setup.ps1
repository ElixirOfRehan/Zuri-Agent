$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
    Write-Host 'Created .env from .env.example. Put DEEPSEEK_API_KEY in it.'
}

uv venv --python 3.12 .venv
uv pip install --python ".venv\Scripts\python.exe" -e ".[dev]"

Write-Host ''
Write-Host 'Setup complete.'
Write-Host 'Run: .\zuri.cmd doctor'
Write-Host 'Run: .\zuri.cmd liar-test'
