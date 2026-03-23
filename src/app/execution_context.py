from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.config.loader import SettingsBundle
from src.logging.structured_logger import StructuredLogger
from src.storage.artifact_store import ArtifactStore


@dataclass
class ExecutionContext:
    artifact_id: str
    input_path: Path
    output_dir: Path
    settings: SettingsBundle
    artifact_store: ArtifactStore
    logger: StructuredLogger
