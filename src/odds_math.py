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

    Each T-n opens at the exact minute (or at post for T-0), never before.
    The previous +0.75 early window froze T-0 ~30s before the off, missing
    last-second steam (e.g. 11.0 captured vs official SP 5.9).
    """
    points = sorted((int(x) for x in (checkpoints or DEFAULT_CHECKPOINTS)), reverse=True)
    if not points:
        return None
    if minutes_to_post > points[0]:
        return None
    extended = points + [points[-1] - 30]
    for high, low in zip(extended[:-1], extended[1:]):
        if high == 0:
            upper = 0.0
            lower = -1.5
        else:
            upper = float(high)
            lower = max(high - 1.5, (high + low) / 2.0)
        if lower < minutes_to_post <= upper:
            return checkpoint_label(high)
    return None


def checkpoint_allows_refresh(checkpoint: str, minutes_to_post: float) -> bool:
    """T-0 keeps overwriting until shortly after post so closing SP replaces the first tick."""
    return str(checkpoint or "").upper() == "T-0" and -1.5 < float(minutes_to_post) <= 0.0
