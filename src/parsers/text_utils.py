from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from src.io.files import read_text_best_effort


DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%m-%d-%y",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%d-%m-%y",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
)

COMMON_CURRENCY_CODES = {
    "AED",
    "AUD",
    "CAD",
    "CHF",
    "CNY",
    "EUR",
    "GBP",
    "HKD",
    "ILS",
    "INR",
    "JPY",
    "KRW",
    "MXN",
    "NOK",
    "NZD",
    "SEK",
    "SGD",
    "TRY",
    "USD",
    "ZAR",
}


@runtime_checkable
class SupportsIsoFormat(Protocol):
    def isoformat(self) -> str: ...


def normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\r", "\n")).strip()


def read_text_file(path: Path) -> str:
    return normalize_whitespace(read_text_best_effort(path))


def _normalize_label_token(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[|:#.\-_/()]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _pipe_segments(line: str) -> list[str]:
    return [segment.strip() for segment in line.split("|") if segment and segment.strip()]


def _extract_inline_value(segment: str, label: str) -> str | None:
    pattern = re.compile(rf"^{re.escape(label)}\s*[:#-]?\s*(.*)$", re.IGNORECASE)
    match = pattern.match(segment.strip())
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _iter_label_matches(text: str, labels: list[str]) -> list[tuple[int, list[str], int, str]]:
    lines = all_lines(text)
    matches: list[tuple[int, list[str], int, str]] = []
    for index, line in enumerate(lines):
        segments = _pipe_segments(line) or [line.strip()]
        normalized_segments = [_normalize_label_token(segment) for segment in segments]
        for label in labels:
            normalized_label = _normalize_label_token(label)
            for segment_index, normalized_segment in enumerate(normalized_segments):
                if normalized_segment == normalized_label or normalized_segment.startswith(f"{normalized_label} "):
                    matches.append((index, segments, segment_index, label))
    return matches


def find_label_value(text: str, labels: list[str]) -> str | None:
    lines = all_lines(text)
    for line_index, segments, segment_index, label in _iter_label_matches(text, labels):
        inline_value = _extract_inline_value(segments[segment_index], label)
        if inline_value:
            return inline_value
        if segment_index + 1 < len(segments):
            return segments[segment_index + 1]
        for lookahead in range(line_index + 1, min(len(lines), line_index + 5)):
            candidate = lines[lookahead].strip()
            if candidate:
                return candidate
    return None


def parse_date(value: object) -> str | None:
    if not value:
        return None
    if isinstance(value, SupportsIsoFormat) and not isinstance(value, str):
        try:
            return value.isoformat()
        except TypeError:
            pass
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(candidate, fmt).date().isoformat()
        except ValueError:
            continue
    match = re.search(r"\d{4}-\d{2}-\d{2}", candidate)
    if match:
        return match.group(0)
    return None


def parse_float(value: object) -> float | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    cleaned = value.strip().replace(",", "")
    cleaned = re.sub(r"^[A-Z]{3}\s+", "", cleaned)
    cleaned = cleaned.replace("$", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_currency(value: object) -> str | None:
    if not value:
        return None
    if not isinstance(value, str):
        return None
    for match in re.finditer(r"\b([A-Z]{3})\b", value.upper()):
        currency = match.group(1)
        if currency in COMMON_CURRENCY_CODES:
            return currency
    return None


def keyword_score(text: str, keywords: list[str]) -> tuple[float, list[str]]:
    lowered = text.lower()
    hits = [keyword for keyword in keywords if keyword.lower() in lowered]
    score = min(1.0, len(hits) * 0.2)
    return score, hits


def all_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def find_money_by_labels(text: str, labels: list[str]) -> float | None:
    lines = all_lines(text)
    for line_index, segments, segment_index, label in _iter_label_matches(text, labels):
        inline_value = _extract_inline_value(segments[segment_index], label)
        if inline_value:
            parsed = parse_float(inline_value)
            if parsed is not None:
                return parsed
        if segment_index + 1 < len(segments):
            parsed = parse_float(segments[segment_index + 1])
            if parsed is not None:
                return parsed
        for lookahead in range(line_index + 1, min(len(lines), line_index + 6)):
            parsed = parse_float(lines[lookahead])
            if parsed is not None:
                return parsed
    return parse_float(find_label_value(text, labels))


def find_date_by_labels(text: str, labels: list[str]) -> str | None:
    lines = all_lines(text)
    for line_index, segments, segment_index, label in _iter_label_matches(text, labels):
        inline_value = _extract_inline_value(segments[segment_index], label)
        if inline_value:
            parsed = parse_date(inline_value)
            if parsed is not None:
                return parsed
        if segment_index + 1 < len(segments):
            parsed = parse_date(segments[segment_index + 1])
            if parsed is not None:
                return parsed
        for lookahead in range(line_index + 1, min(len(lines), line_index + 4)):
            parsed = parse_date(lines[lookahead])
            if parsed is not None:
                return parsed
    return parse_date(find_label_value(text, labels))


def collect_lines_matching(text: str, pattern: str) -> list[str]:
    compiled = re.compile(pattern, re.IGNORECASE)
    return [line for line in all_lines(text) if compiled.search(line)]
