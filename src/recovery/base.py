from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from src.domain.result import ExtractionResult


@dataclass
class RecoveryResult:
    """Recovery payload returned after deterministic extraction is still incomplete."""

    data_patch: dict[str, object] = field(default_factory=dict)
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)


class RecoveryProvider(ABC):
    """Interface for post-deterministic recovery without coupling the pipeline to a specific provider."""

    @abstractmethod
    def recover(
        self,
        original_artifact_path: Path,
        best_deterministic_result: ExtractionResult,
        missing_or_invalid_fields: list[str],
    ) -> RecoveryResult:
        raise NotImplementedError
