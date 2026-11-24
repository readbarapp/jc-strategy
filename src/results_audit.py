"""Checks stored race results against what HKJC place pools must contain."""

from __future__ import annotations

from collections import defaultdict


def expected_place_count(field_size: int) -> int:
    """HKJC PLA pays 3 with 7+ finishers, 2 with 4–6, otherwise the winner only."""
    if field_size >= 7:
        return 3
    if field_size >= 4:
        return 2
    return 1


def _rank(row: dict) -> int:
    try:
        return int(float(row.get("finish_rank") or 0))
    except (TypeError, ValueError):
        return 0


def _dividend(row: dict, field: str) -> float:
    try:
        return float(row.get(field) or 0)
    except (TypeError, ValueError):
        return 0.0


def missing_place_payouts(rows: list[dict]) -> list[dict]:
    """Finishers who should have an official PLA dividend but stored 0."""
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = (
            str(row.get("race_date") or ""),
            str(row.get("venue") or ""),
            str(row.get("race_no") or ""),
        )
        grouped[key].append(row)
    gaps: list[dict] = []
    for horses in grouped.values():
        ranked = [row for row in horses if _rank(row) > 0]
        need = expected_place_count(len(ranked))
        for row in ranked:
            if 1 <= _rank(row) <= need and _dividend(row, "placedividend") <= 0:
                gaps.append(row)
    gaps.sort(key=lambda row: (_rank(row), str(row.get("race_date")), str(row.get("race_no"))))
    return gaps
