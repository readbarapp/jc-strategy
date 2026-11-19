"""Odds drop / 啡格 (brown-grid) calculations."""

from __future__ import annotations

from datetime import datetime
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

# Only 啡格 is kept. Official 1/紅 and 2/綠 are stored as none.
_GRID_ALIASES = {
    "0": GRID_NONE,
    "none": GRID_NONE,
    "n": GRID_NONE,
    "-": GRID_NONE,
    "1": GRID_NONE,
    "red": GRID_NONE,
    "hot": GRID_NONE,
    "hotfavourite": GRID_NONE,
    "2": GRID_NONE,
    "green": GRID_NONE,
    "3": GRID_BROWN,
    "brown": GRID_BROWN,
    "coffee": GRID_BROWN,
}


def parse_hkjc_grid(value) -> str:
    """Official HKJC board colour, collapsed to brown vs not-brown.

    Live `馬號=賠率=標記` codes: 0 none, 1 紅格, 2 綠格, 3 啡格.
    We only keep 3/brown. 紅/綠/大熱 map to none. Empty / unknown → "" so
    callers can fall back to the drop heuristic for historical rows.
    """
    if value is None or value is False:
        return ""
    if value is True:
        return GRID_NONE
    text = str(value).strip().lower()
    if text in {"", "null", "nan"}:
        return ""
    if text in _GRID_ALIASES:
        return _GRID_ALIASES[text]
    try:
        number = int(float(text))
    except ValueError:
        return ""
    return {0: GRID_NONE, 1: GRID_NONE, 2: GRID_NONE, 3: GRID_BROWN}.get(number, "")


def stored_grid(value) -> str:
    """Value written to CSV: brown, none, or blank if the source had no colour."""
    colour = parse_hkjc_grid(value)
    if colour == GRID_BROWN:
        return GRID_BROWN
    if colour == GRID_NONE:
        return GRID_NONE
    return ""


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


def _tick_timestamp(tick: dict):
    text = str(tick.get("ts") or tick.get("capture_timestamp") or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _tick_grid(tick: dict) -> str:
    return parse_hkjc_grid(tick.get("win_grid") if tick.get("win_grid") not in (None, "") else tick.get("hkjc_grid"))


def brown_hold_seconds(ticks: list[dict], end: dict) -> float:
    """How long 啡格 stayed on, ending at `end`, walking backwards along the 10s path.

    A single brown sample (a flash) returns 0. Two samples 10s apart return 10.
    """
    if not ticks or not end or _tick_grid(end) != GRID_BROWN:
        return 0.0

    def sort_key(tick: dict) -> tuple:
        stamp = _tick_timestamp(tick)
        minutes = tick.get("minutes")
        if minutes in (None, ""):
            minutes = tick.get("minutes_to_post")
        try:
            minute_val = -float(minutes)
        except (TypeError, ValueError):
            minute_val = 0.0
        return (stamp or datetime.min, minute_val)

    ordered = sorted(ticks, key=sort_key)
    end_ts = _tick_timestamp(end)
    end_minutes = end.get("minutes")
    if end_minutes in (None, ""):
        end_minutes = end.get("minutes_to_post")
    try:
        end_m = float(end_minutes)
    except (TypeError, ValueError):
        end_m = None
    idx = None
    for i, tick in enumerate(ordered):
        same_ts = end_ts is not None and _tick_timestamp(tick) == end_ts
        try:
            tick_m = float(tick.get("minutes") if tick.get("minutes") not in (None, "") else tick.get("minutes_to_post"))
        except (TypeError, ValueError):
            tick_m = None
        same_m = end_m is not None and tick_m is not None and abs(tick_m - end_m) < 1e-6
        if same_ts or (end_ts is None and same_m) or tick is end:
            idx = i
            if same_ts and same_m:
                break
    if idx is None:
        return 0.0
    start = idx
    while start > 0 and _tick_grid(ordered[start - 1]) == GRID_BROWN:
        start -= 1
    if start == idx:
        return 0.0
    first = _tick_timestamp(ordered[start])
    last = _tick_timestamp(ordered[idx])
    if first and last:
        return round(max(0.0, (last - first).total_seconds()), 1)
    return round(float(idx - start) * 10.0, 1)


def held_brown(
    grid,
    drop_pct: float | None = None,
    threshold: float = 50.0,
    hold_seconds=None,
    hold_need: float = 20.0,
    stored_flag=None,
) -> bool:
    """Official brown at this tick, and (when known) held long enough to be a signal.

    Missing hold_seconds means legacy rows with no 10s path — keep the old gate.
    """
    if not official_brown(grid, drop_pct, threshold, stored_flag):
        return False
    if parse_hkjc_grid(grid) != GRID_BROWN:
        return True
    if hold_seconds in (None, ""):
        return True
    try:
        held = float(hold_seconds)
    except (TypeError, ValueError):
        return True
    return held + 1e-9 >= float(hold_need or 0)


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
