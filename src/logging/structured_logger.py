from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, cast

from src.storage.artifact_store import ArtifactStore


class StructuredLogger:
    def __init__(self, artifact_store: ArtifactStore) -> None:
        self.artifact_store = artifact_store

    def log(self, artifact_id: str, event_type: str, **payload: object) -> None:
        event = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "artifact_id": artifact_id,
            "event_type": event_type,
            "payload": self._normalize(payload),
        }
        self.artifact_store.append_event(artifact_id, event)

    def _normalize(self, value: object) -> object:
        if is_dataclass(value):
            return self._normalize(asdict(cast(Any, value)))
        if isinstance(value, dict):
            return {key: self._normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._normalize(item) for item in value]
        return value
