#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

python3.13 -m venv .venv-hooks
. .venv-hooks/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-hooks.txt
git config core.hooksPath .githooks

echo "Developer hooks are installed. pre-push now runs mypy, ruff, and bandit from .venv-hooks."
