"""Odds drop / 啡格 (brown-grid) calculations."""

from __future__ import annotations

from typing import Iterable


def parse_odds(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number > 0 else None
    text = str(value).strip().upper().replace(",", "")
    if text in {"", "SCR", "SCRATCHED", "---", "--", "N/A", "NA", "0"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number > 0 else None


def win_drop_pct(prev_win_odds, win_odds) -> float:
    """Positive percentage means the win odds shortened (hot money)."""
    prev = parse_odds(prev_win_odds)
    current = parse_odds(win_odds)
    if prev is None or current is None or prev <= 0:
        return 0.0
    drop = (prev - current) / prev * 100.0
    return round(drop, 2)


def is_brown_grid(drop_pct: float, threshold: float) -> bool:
    return float(drop_pct) >= float(threshold)


DEFAULT_CHECKPOINTS = [15, 10, 5, 1, 0]


def checkpoint_label(minutes: int) -> str:
    return f"T-{int(minutes)}"


def match_checkpoint(
    minutes_to_post: float,
    checkpoints: Iterable[int] | None = None,
) -> str | None:
    """Map minutes-to-post onto a named checkpoint.

    Each checkpoint only matches a short window around itself (about ±1.5 min),
    so a 4-minute gap such as T-5 → T-1 is not filled by capturing at T-3.
    Returns None outside those windows.
    """
    points = sorted((int(x) for x in (checkpoints or DEFAULT_CHECKPOINTS)), reverse=True)
    if minutes_to_post > points[0] + 1.5:
        return None
    extended = points + [points[-1] - 30]
    for high, low in zip(extended[:-1], extended[1:]):
        upper = high + 0.75
        lower = max(high - 1.5, (high + low) / 2.0)
        if lower < minutes_to_post <= upper:
            return checkpoint_label(high)
    return None
