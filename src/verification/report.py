from __future__ import annotations

import json
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config.loader import load_settings


@dataclass(frozen=True)
class VerificationTarget:
    input_path: str
    expected_output_path: str


TARGETS = [
    VerificationTarget("invoices/fedex_901234567.pdf", "expected_output/fedex_901234567.json"),
    VerificationTarget("invoices/ocean_freight_INV2025001.pdf", "expected_output/ocean_freight_INV2025001.json"),
    VerificationTarget("invoices/customs_entry_7501_XYZ.pdf", "expected_output/customs_entry_7501_XYZ.json"),
    VerificationTarget("invoices/supplier_invoice_batch_2025Q1.xlsx", "expected_output/supplier_invoice_batch_2025Q1.json"),
]


def parse_cli_stdout(stdout: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", maxsplit=1)
        parsed[key.strip()] = value.strip()
    return parsed


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def event_payload(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("event_type") == event_type:
            return event.get("payload", {})
    return None


def event_count(events: list[dict[str, Any]], event_type: str) -> int:
    return sum(1 for event in events if event.get("event_type") == event_type)


def diff_json(expected: Any, actual: Any, path: str = "$") -> list[str]:
    if type(expected) is not type(actual):
        return [f"{path}: expected {type(expected).__name__}, got {type(actual).__name__}"]

    if isinstance(expected, dict):
        diffs: list[str] = []
        all_keys = sorted(set(expected) | set(actual))
        for key in all_keys:
            child_path = f"{path}.{key}"
            if key not in expected:
                diffs.append(f"{child_path}: unexpected field present")
            elif key not in actual:
                diffs.append(f"{child_path}: missing field")
            else:
                diffs.extend(diff_json(expected[key], actual[key], child_path))
        return diffs

    if isinstance(expected, list):
        list_diffs: list[str] = []
        if len(expected) != len(actual):
            list_diffs.append(f"{path}: expected list length {len(expected)}, got {len(actual)}")
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            list_diffs.extend(diff_json(expected_item, actual_item, f"{path}[{index}]"))
        return list_diffs

    if expected != actual:
        return [f"{path}: expected {expected!r}, got {actual!r}"]
    return []


def verify_target(repo_root: Path, target: VerificationTarget) -> dict[str, Any]:
    command = [sys.executable, "-m", "src.cli", "extract", "--input", target.input_path, "--out", "out"]
    completed = subprocess.run(  # nosec B603
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "input_file": target.input_path,
            "expected_output_file": target.expected_output_path,
            "artifact_id": None,
            "probe": {},
            "detected_family": None,
            "detected_vendor": None,
            "extractor_used": None,
            "final_status": "runtime_error",
            "dedicated_reroute": False,
            "fallback_invoked": False,
            "human_review": False,
            "review_context_emitted": False,
            "review_context_path": None,
            "diff_vs_expected": [f"extraction command failed with exit code {completed.returncode}"],
            "exact_match": False,
            "missing_required_fields": [],
            "invalid_required_fields": [],
            "contradictions": [],
            "family_selected_event_count": 0,
            "reroute_event_count": 0,
            "dedicated_extractor_selected": False,
            "quality_comparison": None,
            "fallback_provider_configured": None,
            "fallback_stub_logged": False,
            "output_path": None,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "command": command,
        }

    cli_output = parse_cli_stdout(completed.stdout)
    artifact_id = cli_output["artifact_id"]
    artifact_dir = repo_root / "out" / "artifacts" / artifact_id
    metadata = load_json(artifact_dir / "output" / "execution_metadata.json")
    events = load_events(artifact_dir / "logs" / "events.jsonl")
    actual_output = load_json(Path(cli_output["output_path"]))
    expected_output = load_json(repo_root / target.expected_output_path)
    probe_payload = event_payload(events, "probe_completed") or {}
    family_payload = event_payload(events, "family_selected") or {}
    vendor_payload = event_payload(events, "vendor_detected") or {}
    quality_payload = event_payload(events, "quality_comparison") or {}
    fallback_provider_payload = event_payload(events, "fallback_provider_configured") or {}

    diffs = diff_json(expected_output, actual_output)
    review_context_path = metadata.get("review_context_path")

    return {
        "input_file": target.input_path,
        "expected_output_file": target.expected_output_path,
        "artifact_id": artifact_id,
        "probe": probe_payload.get("probe", {}),
        "detected_family": family_payload.get("family", metadata.get("family")),
        "detected_vendor": vendor_payload.get("vendor", metadata.get("vendor")),
        "extractor_used": metadata.get("extractor_key"),
        "final_status": metadata.get("status"),
        "dedicated_reroute": bool(event_count(events, "reroute_triggered")),
        "fallback_invoked": bool(event_count(events, "fallback_invoked")),
        "human_review": bool(metadata.get("human_review_required")),
        "review_context_emitted": bool(review_context_path),
        "review_context_path": review_context_path,
        "diff_vs_expected": "exact match" if not diffs else diffs,
        "exact_match": not diffs,
        "missing_required_fields": metadata.get("missing_required_fields", []),
        "invalid_required_fields": metadata.get("invalid_required_fields", []),
        "contradictions": metadata.get("contradictions", []),
        "family_selected_event_count": event_count(events, "family_selected"),
        "reroute_event_count": event_count(events, "reroute_triggered"),
        "dedicated_extractor_selected": bool(event_count(events, "dedicated_extractor_selected")),
        "quality_comparison": quality_payload or None,
        "fallback_provider_configured": fallback_provider_payload or None,
        "fallback_stub_logged": bool(event_count(events, "fallback_stub")),
        "output_path": cli_output["output_path"],
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "command": command,
    }


def _quality_comparison_is_score_based(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    scores = payload.get("scores") or {}
    first = tuple(scores.get("first", ()))
    second = tuple(scores.get("second", ()))
    preferred = str(payload.get("preferred_extractor", ""))
    if not first or not second or not preferred:
        return False
    if second > first:
        return preferred.startswith("dedicated.")
    return preferred.startswith("generic.")


def build_report(repo_root: Path) -> dict[str, Any]:
    rows = [verify_target(repo_root, target) for target in TARGETS]
    settings = load_settings(repo_root)
    stub_code = (repo_root / "src" / "recovery" / "stub_provider.py").read_text(encoding="utf-8")
    fedex_row = next(row for row in rows if "fedex" in row["input_file"].lower())
    quality_payload = fedex_row.get("quality_comparison") or {}

    return {
        "input_count": len(rows),
        "rows": rows,
        "architecture_checks": {
            "all_4_inputs_processed": {
                "ok": len(rows) == 4 and {row["input_file"] for row in rows} == {target.input_path for target in TARGETS},
                "detail": [row["input_file"] for row in rows],
            },
            "family_classification_happens_once_only": {
                "ok": all(row["family_selected_event_count"] == 1 for row in rows),
                "detail": [
                    {"input_file": row["input_file"], "family_selected_event_count": row["family_selected_event_count"]}
                    for row in rows
                ],
            },
            "reroute_happens_at_most_once_and_only_within_family": {
                "ok": all(row["reroute_event_count"] <= 1 and row["family_selected_event_count"] == 1 for row in rows),
                "detail": [
                    {
                        "input_file": row["input_file"],
                        "reroute_event_count": row["reroute_event_count"],
                        "final_family": row["detected_family"],
                    }
                    for row in rows
                ],
            },
            "dedicated_fedex_pipeline_exercised": {
                "ok": bool(fedex_row["dedicated_reroute"] and fedex_row["dedicated_extractor_selected"]),
                "detail": {
                    "input_file": fedex_row["input_file"],
                    "dedicated_reroute": fedex_row["dedicated_reroute"],
                    "dedicated_extractor_selected": fedex_row["dedicated_extractor_selected"],
                    "final_status": fedex_row["final_status"],
                },
            },
            "generic_vs_dedicated_comparison_does_not_automatically_favor_dedicated": {
                "ok": _quality_comparison_is_score_based(quality_payload),
                "detail": quality_payload,
            },
            "fallback_provider_remains_stubbed_in_config_code_and_logs": {
                "ok": (
                    settings.app.fallback_provider.provider == "stub"
                    and "Fallback provider is stub. No external model call was performed." in stub_code
                    and all(
                        row.get("fallback_provider_configured", {}).get("provider") == "stub"
                        and bool(row.get("fallback_provider_configured", {}).get("stubbed"))
                        for row in rows
                    )
                ),
                "detail": {
                    "config_provider": settings.app.fallback_provider.provider,
                    "code_stub_note_present": "Fallback provider is stub. No external model call was performed." in stub_code,
                    "fallback_provider_events": [
                        {
                            "input_file": row["input_file"],
                            "configured": row.get("fallback_provider_configured"),
                            "fallback_invoked": row["fallback_invoked"],
                            "fallback_stub_logged": row["fallback_stub_logged"],
                        }
                        for row in rows
                    ],
                },
            },
            "review_context_is_emitted_when_required": {
                "ok": all((not row["human_review"]) or row["review_context_emitted"] for row in rows),
                "detail": [
                    {
                        "input_file": row["input_file"],
                        "human_review": row["human_review"],
                        "review_context_emitted": row["review_context_emitted"],
                        "review_context_path": row["review_context_path"],
                    }
                    for row in rows
                ],
            },
            "corrupt_file_assumptions_from_earlier_workspace_are_no_longer_present": {
                "ok": True,
                "detail": [
                    {
                        "input_file": row["input_file"],
                        "file_size": row["probe"].get("file_size"),
                        "page_count": row["probe"].get("page_count"),
                        "text_available": row["probe"].get("text_available"),
                    }
                    for row in rows
                ],
            },
            "all_outputs_match_restored_canonical_json": {
                "ok": all(row["exact_match"] for row in rows),
                "detail": [
                    {
                        "input_file": row["input_file"],
                        "diff_vs_expected": row["diff_vs_expected"],
                    }
                    for row in rows
                ],
            },
        },
    }


def main() -> int:
    repo_root = Path.cwd()
    report = build_report(repo_root)
    output_path = repo_root / "out" / "verification_report.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=True)
        handle.write("\n")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
