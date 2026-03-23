from __future__ import annotations

import json
from pathlib import Path

from src.io.files import copy_file, ensure_directory
from src.io.json_codec import write_json
from src.storage.artifact_store import ArtifactStore


class LocalArtifactStore(ArtifactStore):
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        ensure_directory(self.base_dir)

    def artifact_root(self, artifact_id: str) -> Path:
        return self.base_dir / artifact_id

    def store_input(self, artifact_id: str, input_path: Path) -> Path:
        destination = self.artifact_root(artifact_id) / "input" / f"original{input_path.suffix}"
        return copy_file(input_path, destination)

    def write_output_json(self, artifact_id: str, payload: object) -> Path:
        return write_json(self.artifact_root(artifact_id) / "output" / "extracted.json", payload)

    def write_execution_metadata(self, artifact_id: str, payload: object) -> Path:
        return write_json(self.artifact_root(artifact_id) / "output" / "execution_metadata.json", payload)

    def append_event(self, artifact_id: str, event: object) -> Path:
        log_path = self.artifact_root(artifact_id) / "logs" / "events.jsonl"
        ensure_directory(log_path.parent)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True))
            handle.write("\n")
        return log_path

    def write_review_context(self, artifact_id: str, payload: object) -> Path:
        return write_json(self.artifact_root(artifact_id) / "review" / "context.json", payload)
