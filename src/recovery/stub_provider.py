from __future__ import annotations

from pathlib import Path
from typing import override

from src.domain.result import ExtractionResult
from src.recovery.base import RecoveryProvider, RecoveryResult


class StubRecoveryProvider(RecoveryProvider):
    """No-op recovery implementation used by the verified baseline solution."""

    @override
    def recover(
        self,
        original_artifact_path: Path,
        best_deterministic_result: ExtractionResult,
        missing_or_invalid_fields: list[str],
    ) -> RecoveryResult:
        # This stub makes fallback behavior observable in artifacts and logs
        # without implying that an external recovery system was exercised.
        return RecoveryResult(
            data_patch={},
            confidence=0.0,
            notes=[
                "Fallback provider is stub. No external model call was performed.",
                f"Unresolved fields: {', '.join(missing_or_invalid_fields) if missing_or_invalid_fields else 'none'}",
            ],
        )
