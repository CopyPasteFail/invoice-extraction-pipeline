from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.domain.models import ExtractionPayload, Extras
from src.routing.probe import ProbeResult


class BaseExtractor(ABC):
    key: str
    family: str

    @abstractmethod
    def extract(self, input_path: Path, probe: ProbeResult) -> ExtractionPayload:
        raise NotImplementedError

    def build_extras(self, note: str | None = None) -> Extras:
        return Extras()
