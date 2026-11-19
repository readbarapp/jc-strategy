"""Canonical CSV schemas for odds snapshots and official results."""

from __future__ import annotations

ODDS_FIELDS = [
    "race_date",
    "venue",
    "race_no",
    "scheduled_time",
    "checkpoint",
    "capture_timestamp",
    "minutes_to_post",
    "horse_no",
    "horse_name",
    "win_odds",
    "place_odds",
    "prev_win_odds",
    "win_drop_pct",
    "is_brown_grid",
    "hkjc_grid",
    "place_grid",
    "brown_hold_seconds",
]

TICK_FIELDS = [
    "race_date",
    "venue",
    "race_no",
    "scheduled_time",
    "capture_timestamp",
    "minutes_to_post",
    "horse_no",
    "horse_name",
    "win_odds",
    "place_odds",
    "hkjc_grid",
    "place_grid",
]

RESULTS_FIELDS = [
    "race_date",
    "venue",
    "race_no",
    "horse_no",
    "horse_name",
    "finish_rank",
    "final_sp",
    "win_dividend",
    "placedividend",
]

VENUE_NAMES = {"ST": "沙田", "HV": "跑馬地"}

# Display checkpoints: one column each on the odds board (one row per horse).
DISPLAY_CHECKPOINTS = ["T-15", "T-10", "T-5", "T-1", "T-0"]
