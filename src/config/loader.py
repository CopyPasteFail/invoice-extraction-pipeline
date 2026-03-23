from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias, cast

import yaml


@dataclass
class ArtifactStoreConfig:
    provider: str
    base_dir: str


@dataclass
class FallbackProviderConfig:
    provider: str


@dataclass
class AppConfig:
    output_dir: str
    vendor_routing_confidence_threshold: float
    fallback_confidence_threshold: float
    allow_within_family_reroute_once: bool
    allow_family_reroute: bool
    always_include_empty_arrays: bool
    artifact_store: ArtifactStoreConfig
    fallback_provider: FallbackProviderConfig


@dataclass
class VendorRouteConfig:
    confidence_threshold: float
    dedicated_extractor: str


@dataclass
class FamilyRouteConfig:
    generic_extractor: str
    vendor_detection_enabled: bool
    vendor_confidence_threshold: float
    vendors: dict[str, VendorRouteConfig]


@dataclass
class RoutingConfig:
    families: dict[str, FamilyRouteConfig]


@dataclass
class ConditionalRule:
    when: str
    require: list[str]


@dataclass
class FamilyFieldPolicy:
    required: list[str]
    important: list[str]
    optional: list[str]
    conditional: list[ConditionalRule]


@dataclass
class SettingsBundle:
    app: AppConfig
    routing: RoutingConfig
    field_policies: dict[str, FamilyFieldPolicy]


YamlValue: TypeAlias = object
YamlMap: TypeAlias = dict[str, YamlValue]


def _as_map(value: object) -> YamlMap:
    return cast(YamlMap, value) if isinstance(value, dict) else {}


def _as_string_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _as_str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _as_float(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float, str)) else default


def _as_bool(value: object, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _load_yaml(path: Path) -> YamlMap:
    with path.open("r", encoding="utf-8") as handle:
        return _as_map(yaml.safe_load(handle) or {})


def load_settings(base_dir: Path) -> SettingsBundle:
    config_dir = base_dir / "config"

    app_raw = _as_map(_load_yaml(config_dir / "app.yaml").get("app"))
    routing_raw = _as_map(_load_yaml(config_dir / "routing.yaml").get("families"))
    policies_raw = _load_yaml(config_dir / "field_policies.yaml")

    app_config = AppConfig(
        output_dir=_as_str(app_raw.get("output_dir")),
        vendor_routing_confidence_threshold=_as_float(app_raw.get("vendor_routing_confidence_threshold")),
        fallback_confidence_threshold=_as_float(app_raw.get("fallback_confidence_threshold")),
        allow_within_family_reroute_once=_as_bool(app_raw.get("allow_within_family_reroute_once")),
        allow_family_reroute=_as_bool(app_raw.get("allow_family_reroute")),
        always_include_empty_arrays=_as_bool(app_raw.get("always_include_empty_arrays")),
        artifact_store=ArtifactStoreConfig(
            provider=_as_str(_as_map(app_raw.get("artifact_store")).get("provider")),
            base_dir=_as_str(_as_map(app_raw.get("artifact_store")).get("base_dir")),
        ),
        fallback_provider=FallbackProviderConfig(
            provider=_as_str(_as_map(app_raw.get("fallback_provider")).get("provider")),
        ),
    )

    routing_config = RoutingConfig(
        families={
            family_name: FamilyRouteConfig(
                generic_extractor=_as_str(_as_map(family_payload).get("generic_extractor")),
                vendor_detection_enabled=_as_bool(_as_map(family_payload).get("vendor_detection_enabled"), True),
                vendor_confidence_threshold=_as_float(
                    _as_map(family_payload).get(
                        "vendor_confidence_threshold",
                        app_config.vendor_routing_confidence_threshold,
                    )
                ),
                vendors={
                    vendor_name: VendorRouteConfig(
                        confidence_threshold=_as_float(
                            _as_map(vendor_payload).get(
                                "confidence_threshold",
                                _as_map(family_payload).get(
                                    "vendor_confidence_threshold",
                                    app_config.vendor_routing_confidence_threshold,
                                ),
                            )
                        ),
                        dedicated_extractor=_as_str(_as_map(vendor_payload).get("dedicated_extractor")),
                    )
                    for vendor_name, vendor_payload in _as_map(_as_map(family_payload).get("vendors")).items()
                },
            )
            for family_name, family_payload in routing_raw.items()
        }
    )

    field_policies = {
        family_name: FamilyFieldPolicy(
            required=_as_string_list(payload.get("required")),
            important=_as_string_list(payload.get("important")),
            optional=_as_string_list(payload.get("optional")),
            conditional=[
                ConditionalRule(when=str(item["when"]), require=_as_string_list(item.get("require")))
                for item in cast(list[YamlMap], payload.get("conditional", []))
                if "when" in item
            ],
        )
        for family_name, raw_payload in policies_raw.items()
        for payload in [_as_map(raw_payload)]
    }

    return SettingsBundle(app=app_config, routing=routing_config, field_policies=field_policies)
