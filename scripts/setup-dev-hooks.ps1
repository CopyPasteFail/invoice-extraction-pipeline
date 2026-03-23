$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path ".venv-hooks")) {
    py -3.13 -m venv .venv-hooks
}

& .\.venv-hooks\Scripts\python.exe -m pip install --upgrade pip
& .\.venv-hooks\Scripts\python.exe -m pip install -r requirements.txt -r requirements-hooks.txt
git config core.hooksPath .githooks

Write-Output "Developer hooks are installed. pre-push now runs mypy, ruff, and bandit from .venv-hooks."
