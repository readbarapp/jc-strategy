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
    """Legacy 啡格 heuristic: drop vs the previous checkpoint ≥ threshold.

    New snapshots store HKJC's own board colour in `hkjc_grid`. Use
    `official_brown` so strategy / display follow the betting app, not this
    50% assumption, whenever that colour is known.
    """
    return float(drop_pct) >= float(threshold)


GRID_NONE = "none"
GRID_RED = "red"
GRID_GREEN = "green"
GRID_BROWN = "brown"

_GRID_ALIASES = {
    "0": GRID_NONE,
    "none": GRID_NONE,
    "n": GRID_NONE,
    "-": GRID_NONE,
    "1": GRID_RED,
    "red": GRID_RED,
    "hot": GRID_RED,
    "hotfavourite": GRID_RED,
    "2": GRID_GREEN,
    "green": GRID_GREEN,
    "3": GRID_BROWN,
    "brown": GRID_BROWN,
    "coffee": GRID_BROWN,
}


def parse_hkjc_grid(value) -> str:
    """Official HKJC board colour from getJSON's third field or GraphQL oddsDropValue.

    Live `馬號=賠率=標記` codes: 0 none, 1 紅格/大熱, 2 綠格, 3 啡格.
    Empty / unknown → "" so callers can fall back to the drop heuristic for
    historical rows that never stored a grid.
    """
    if value is None or value is False:
        return ""
    if value is True:
        return GRID_RED
    text = str(value).strip().lower()
    if text in {"", "null", "nan"}:
        return ""
    if text in _GRID_ALIASES:
        return _GRID_ALIASES[text]
    try:
        number = int(float(text))
    except ValueError:
        return ""
    return {0: GRID_NONE, 1: GRID_RED, 2: GRID_GREEN, 3: GRID_BROWN}.get(number, "")


def official_brown(
    grid,
    drop_pct: float | None = None,
    threshold: float = 50.0,
    stored_flag=None,
) -> bool:
    """Brown only when HKJC painted 啡格. Legacy empty grid keeps the drop / stored flag."""
    colour = parse_hkjc_grid(grid)
    if colour == GRID_BROWN:
        return True
    if colour in {GRID_NONE, GRID_RED, GRID_GREEN}:
        return False
    if str(stored_flag or "").strip().lower() in {"1", "true", "yes", "y"}:
        return True
    return is_brown_grid(float(drop_pct or 0), threshold)


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
