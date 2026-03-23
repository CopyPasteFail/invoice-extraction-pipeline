from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ArtifactStore(ABC):
    @abstractmethod
    def store_input(self, artifact_id: str, input_path: Path) -> Path:
        raise NotImplementedError

    @abstractmethod
    def write_output_json(self, artifact_id: str, payload: object) -> Path:
        raise NotImplementedError

    @abstractmethod
    def write_execution_metadata(self, artifact_id: str, payload: object) -> Path:
        raise NotImplementedError

    @abstractmethod
    def append_event(self, artifact_id: str, event: object) -> Path:
        raise NotImplementedError

    @abstractmethod
    def write_review_context(self, artifact_id: str, payload: object) -> Path:
        raise NotImplementedError

    @abstractmethod
    def artifact_root(self, artifact_id: str) -> Path:
        raise NotImplementedError
