from __future__ import annotations

from pathlib import Path

from src.config.loader import SettingsBundle
from src.routing.family_classifier import FamilyClassifier
from src.routing.probe import ProbeResult
from src.routing.routing_decision import RoutingDecision
from src.routing.vendor_detector import VendorDetector


class Router:
    """Coordinates one family decision and optional within-family vendor lookup."""

    settings: SettingsBundle
    family_classifier: FamilyClassifier
    vendor_detector: VendorDetector

    def __init__(self, settings: SettingsBundle) -> None:
        self.settings = settings
        self.family_classifier = FamilyClassifier()
        self.vendor_detector = VendorDetector()

    def route_initial(self, artifact_id: str, input_path: Path, probe: ProbeResult) -> RoutingDecision:
        # The initial route establishes the family once and selects the family's
        # generic extractor. Vendor detection only refines routing within that family.
        family_choice = self.family_classifier.classify(input_path, probe)
        family_config = self.settings.routing.families[family_choice.family]
        if family_config.vendor_detection_enabled:
            vendor_detection = self.vendor_detector.detect(family_choice.family, input_path, probe)
        else:
            vendor_detection = self.vendor_detector.detect_unknown()

        return RoutingDecision(
            artifact_id=artifact_id,
            family=family_choice.family,
            family_confidence=family_choice.confidence,
            vendor=vendor_detection.vendor,
            vendor_confidence=vendor_detection.confidence,
            generic_extractor_key=family_config.generic_extractor,
            family_evidence=family_choice.evidence,
            vendor_evidence=vendor_detection.evidence,
        )

    def redetect_vendor(self, family: str, input_path: Path, probe: ProbeResult, extra_text: str) -> tuple[str, float, list[str]]:
        # Reroute is limited to vendor refinement inside the same family.
        family_config = self.settings.routing.families[family]
        if not family_config.vendor_detection_enabled:
            detection = self.vendor_detector.detect_unknown()
            return detection.vendor, detection.confidence, detection.evidence
        detection = self.vendor_detector.detect(family, input_path, probe, extra_text=extra_text)
        return detection.vendor, detection.confidence, detection.evidence
