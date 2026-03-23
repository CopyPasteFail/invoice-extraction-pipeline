from __future__ import annotations

import shutil
from pathlib import Path


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def copy_file(source: Path, destination: Path) -> Path:
    ensure_directory(destination.parent)
    shutil.copy2(source, destination)
    return destination


def read_text_best_effort(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1", errors="ignore")
