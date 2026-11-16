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


def checkpoint_label(minutes: int) -> str:
    return f"T-{int(minutes)}"


def match_checkpoint(
    minutes_to_post: float,
    checkpoints: Iterable[int] | None = None,
) -> str | None:
    """Map minutes-to-post into a T-n window. Returns None if outside racing window."""
    points = sorted((int(x) for x in (checkpoints or [15, 10, 5, 3, 1, 0])), reverse=True)
    if minutes_to_post > points[0] + 1.5:
        return None
    # Half-open windows between consecutive checkpoints, last window down to well after post.
    bounds = points + [-30]
    for high, low in zip(bounds[:-1], bounds[1:]):
        mid = (high + low) / 2.0
        if minutes_to_post > mid:
            return checkpoint_label(high)
    return checkpoint_label(points[-1])
