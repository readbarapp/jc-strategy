"""Classify HKJC meeting/race/horse states so we do not store junk snapshots."""

from __future__ import annotations

import re
from datetime import datetime

from .odds_math import parse_odds

POST_SHIFT_MINUTES = 2.0
FINISHED_GRACE_MINUTES = 5.0
MAX_DELAY_EXTEND_MINUTES = 180
KEEP_ALIVE_MINUTES = 10

_OFF = ("abandon", "cancel", "void", "postpon", "norace")
_RESULTED = ("result", "finalised", "finalized", "official")
_SCRATCH = ("scratch", "withdraw", "standby", "reserve")


def compact_status(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def is_meeting_off(status: str) -> bool:
    return any(token in compact_status(status) for token in _OFF)


def is_race_off(status: str) -> bool:
    """Cancelled / abandoned / void / postponed — do not capture or harvest junk."""
    return any(token in compact_status(status) for token in _OFF)


def is_race_resulted(status: str) -> bool:
    return any(token in compact_status(status) for token in _RESULTED)


def is_horse_scratched(status: str) -> bool:
    return any(token in compact_status(status) for token in _SCRATCH)


def has_tradable_win(win_odds) -> bool:
    return parse_odds(win_odds) is not None


def should_write_runner(status: str, win_odds) -> bool:
    """Only persist a checkpoint if the horse is still in and has a real WIN price."""
    return (not is_horse_scratched(status)) and has_tradable_win(win_odds)


def post_times_shifted(old: datetime | None, new: datetime | None, threshold_minutes: float = POST_SHIFT_MINUTES) -> bool:
    if new is None:
        return False
    if old is None:
        return True
    return abs((new - old).total_seconds()) >= float(threshold_minutes) * 60.0


def race_is_over(status: str, minutes_to_post: float | None, grace_minutes: float = FINISHED_GRACE_MINUTES) -> bool:
    """Stop polling a race only when HKJC says it is done, not merely because the old clock passed."""
    if is_race_off(status) or is_race_resulted(status):
        return True
    return False


def should_extend_watch(status: str, minutes_to_post: float | None) -> bool:
    """Keep the job alive if advertised post time passed but the race is still declared."""
    if is_race_off(status) or is_race_resulted(status):
        return False
    if minutes_to_post is None:
        return True
    return minutes_to_post < 0
