"""Pick checkpoint samples from a dense 10s tick path, not the first glimpse of a window."""

from __future__ import annotations

from .odds_math import DEFAULT_CHECKPOINTS, checkpoint_label

TICK_WINDOW_BEFORE = 16.0
TICK_WINDOW_AFTER = 1.5
FINALIZE_LAG = 0.4
SEARCH_RADIUS = 0.75


def in_tick_window(minutes_to_post: float | None) -> bool:
    if minutes_to_post is None:
        return False
    return -TICK_WINDOW_AFTER < float(minutes_to_post) <= TICK_WINDOW_BEFORE


def target_is_frozen(now_minutes: float, target: float) -> bool:
    """True once we have passed the mark long enough to have ticks on both sides."""
    if target == 0:
        return float(now_minutes) <= -0.75
    return float(now_minutes) <= float(target) - FINALIZE_LAG


def best_tick_for_target(ticks: list[dict], target: float) -> dict | None:
    """Choose the tick whose minutes_to_post is closest to the exact checkpoint.

    T-n (n>0): only ticks around the mark, slightly preferring at-or-after the minute.
    T-0: the last tick at or after post (minutes <= 0), i.e. closest to the off from below.
    """
    if not ticks:
        return None
    if float(target) == 0:
        eligible = [tick for tick in ticks if -TICK_WINDOW_AFTER < float(tick["minutes"]) <= 0.02]
        if not eligible:
            return None
        # Latest quote after the off — steam often continues until betting closes.
        return min(eligible, key=lambda tick: float(tick["minutes"]))
    lo = float(target) - SEARCH_RADIUS
    hi = float(target) + 0.08
    eligible = [tick for tick in ticks if lo < float(tick["minutes"]) <= hi]
    if not eligible:
        return None
    reached = [tick for tick in eligible if float(tick["minutes"]) <= float(target)]
    pool = reached or eligible
    return min(pool, key=lambda tick: abs(float(tick["minutes"]) - float(target)))


def due_targets(
    now_minutes: float,
    checkpoints: list[int] | None = None,
    *,
    refresh_t0: bool = True,
) -> list[int]:
    """Checkpoint minute-marks that should emit a snapshot on this tick.

    T-n stays open across the search radius so we can replace an early sample
    with a closer one. T-0 only opens at/after post.
    """
    points = [int(x) for x in (checkpoints or DEFAULT_CHECKPOINTS)]
    now = float(now_minutes)
    due: list[int] = []
    for target in points:
        if target == 0:
            if refresh_t0 and -TICK_WINDOW_AFTER < now <= 0.02:
                due.append(0)
            continue
        if now <= float(target) + 0.08 and now > float(target) - SEARCH_RADIUS:
            due.append(target)
    return due


def checkpoint_names(checkpoints: list[int] | None = None) -> list[str]:
    return [checkpoint_label(int(n)) for n in (checkpoints or DEFAULT_CHECKPOINTS)]
