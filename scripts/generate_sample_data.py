#!/usr/bin/env python3
"""Deterministic sample odds + results so the Pages dashboard works immediately."""

from __future__ import annotations

import math
import random
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.csv_store import copy_to_docs, write_rows  # noqa: E402
from src.odds_math import is_brown_grid, win_drop_pct  # noqa: E402
from src.schema import ODDS_FIELDS, RESULTS_FIELDS  # noqa: E402
from src.timeutil import combine_hk  # noqa: E402

HORSES = [
    "GOLDEN JOURNEY", "SILENT STORM", "LUCKY STAR", "PACIFIC PEARL",
    "DRAGON FIRE", "HARMONY KING", "FORTUNE WHEEL", "CELESTIAL PATH",
    "IRON WARRIOR", "RED FORTUNE", "WINNING HEART", "MOONLIT BAY",
    "SUPER EXPRESS", "TRUE BELIEVER", "RAPID ARROW", "SKYLINE DREAM",
    "MIGHTY RIVER", "SUNLIT PEAK", "GRAND PARADE", "NOBLE SPIRIT",
    "EASTERN WIND", "BRAVE LEGEND", "SILVER LINING", "TURBO CHARGE",
    "VICTORY LANE", "STARLIGHT RUN", "KING'S SHIELD", "OCEAN PRIDE",
    "FLASH POINT", "GREEN JADE", "ROYAL BANNER", "NIGHT RAID",
]

MEETINGS = [
    ("2026-10-15", "HV", "19:15", 8),
    ("2026-10-19", "ST", "13:00", 10),
    ("2026-10-22", "HV", "19:15", 8),
    ("2026-10-26", "ST", "13:00", 10),
    ("2026-11-01", "ST", "13:00", 10),
    ("2026-11-05", "HV", "19:15", 8),
    ("2026-11-08", "ST", "13:00", 10),
    ("2026-11-12", "HV", "19:15", 8),
    ("2026-11-15", "ST", "13:00", 10),
]

CHECKPOINTS = [15, 10, 5, 3, 1, 0]
THRESHOLD = 50.0


def _opening_book(rng: random.Random, field: int) -> list[float]:
    weights = [rng.paretovariate(1.35) for _ in range(field)]
    total = sum(weights)
    implied = [w / total * 1.22 for w in weights]  # ~122% overround
    odds = [max(1.6, min(99.0, round(1.0 / p, 1))) for p in implied]
    return odds


def _step_odds(
    rng: random.Random,
    odds: list[float],
    steamer: int | None,
    crash: bool = False,
) -> list[float]:
    nxt = []
    for i, price in enumerate(odds):
        if crash and steamer is not None and i == steamer:
            factor = rng.uniform(0.32, 0.48)  # 52–68% drop → 啡格
            nxt.append(max(1.5, min(99.0, round(price * factor, 1))))
            continue
        shock = rng.gauss(0, 0.04)
        if steamer is not None and i == steamer:
            shock -= abs(rng.gauss(0.03, 0.02))
        elif steamer is not None:
            shock += abs(rng.gauss(0.015, 0.015))
        moved = price * math.exp(shock)
        nxt.append(max(1.4, min(99.0, round(moved, 1))))
    return nxt


def _place_from_win(win: float, rng: random.Random) -> float:
    factor = 0.38 + rng.random() * 0.12
    return max(1.1, round(win * factor, 1))


def _finish_order(rng: random.Random, t0: list[float]) -> list[int]:
    inv = [1.0 / p for p in t0]
    remaining = list(range(len(t0)))
    order = []
    while remaining:
        weights = [inv[i] for i in remaining]
        total = sum(weights)
        pick = rng.random() * total
        acc = 0.0
        chosen = remaining[-1]
        for i, w in zip(remaining, weights):
            acc += w
            if acc >= pick:
                chosen = i
                break
        order.append(chosen)
        remaining.remove(chosen)
    return order


def generate(seed: int = 20261116) -> None:
    rng = random.Random(seed)
    odds_rows: list[dict] = []
    result_rows: list[dict] = []

    for race_date, venue, first_time, n_races in MEETINGS:
        first = combine_hk(race_date, first_time)
        for race_no in range(1, n_races + 1):
            post = first + timedelta(minutes=(race_no - 1) * 35)
            scheduled = post.strftime("%H:%M:%S")
            field = 12 if venue == "HV" else 14
            names = HORSES[:]
            rng.shuffle(names)
            names = names[:field]
            opening = _opening_book(rng, field)
            mid_band = [i for i, price in enumerate(opening) if 6.0 <= price <= 22.0]
            steamer = rng.choice(mid_band) if mid_band and rng.random() < 0.88 else None
            crash_step = rng.choice([2, 3, 4]) if steamer is not None else -1
            path = [opening]
            prices = opening[:]
            for step_i, _ in enumerate(CHECKPOINTS[1:], start=1):
                prices = _step_odds(rng, prices, steamer, crash=(step_i == crash_step))
                path.append(prices[:])

            t0 = path[-1]
            order = _finish_order(rng, t0)
            ranks = {idx: rank + 1 for rank, idx in enumerate(order)}
            place_n = 3 if field >= 7 else 2
            winner = order[0]
            win_div = round(t0[winner] * 10, 1)
            place_divs = {}
            for idx in order[:place_n]:
                place_divs[idx] = round(_place_from_win(t0[idx], rng) * 10, 1)

            for cp_i, minutes_before in enumerate(CHECKPOINTS):
                capture = post - timedelta(minutes=minutes_before)
                for horse_i in range(field):
                    win = path[cp_i][horse_i]
                    prev = path[cp_i - 1][horse_i] if cp_i else win
                    drop = win_drop_pct(prev, win)
                    odds_rows.append(
                        {
                            "race_date": race_date,
                            "venue": venue,
                            "race_no": race_no,
                            "scheduled_time": scheduled,
                            "checkpoint": f"T-{minutes_before}",
                            "capture_timestamp": capture.strftime("%Y-%m-%d %H:%M:%S"),
                            "horse_no": horse_i + 1,
                            "horse_name": names[horse_i],
                            "win_odds": win,
                            "place_odds": _place_from_win(win, rng),
                            "prev_win_odds": prev,
                            "win_drop_pct": drop,
                            "is_brown_grid": "true" if is_brown_grid(drop, THRESHOLD) else "false",
                        }
                    )

            for horse_i in range(field):
                result_rows.append(
                    {
                        "race_date": race_date,
                        "venue": venue,
                        "race_no": race_no,
                        "horse_no": horse_i + 1,
                        "horse_name": names[horse_i],
                        "finish_rank": ranks[horse_i],
                        "final_sp": t0[horse_i],
                        "win_dividend": win_div if horse_i == winner else 0,
                        "placedividend": place_divs.get(horse_i, 0),
                    }
                )

    write_rows(ROOT / "data" / "odds_snapshots.csv", ODDS_FIELDS, odds_rows)
    write_rows(ROOT / "data" / "race_results.csv", RESULTS_FIELDS, result_rows)
    copy_to_docs()
    print(f"Wrote {len(odds_rows)} odds rows and {len(result_rows)} result rows")


if __name__ == "__main__":
    generate()
