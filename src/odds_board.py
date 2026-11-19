"""Pivot checkpoint snapshots into one row per horse, separately for WIN and PLACE."""

from __future__ import annotations

from .odds_math import official_brown, parse_hkjc_grid, parse_odds, win_drop_pct

CHECKPOINTS = ["T-15", "T-10", "T-5", "T-1", "T-0"]
CP_SUFFIX = {
    "T-15": "t15",
    "T-10": "t10",
    "T-5": "t5",
    "T-1": "t1",
    "T-0": "t0",
}
WIDE_FIELDS = [
    "pool",
    "race_date",
    "venue",
    "race_no",
    "scheduled_time",
    "horse_no",
    "horse_name",
    "odds_t15",
    "odds_t10",
    "odds_t5",
    "odds_t1",
    "odds_t0",
    "grid_t15",
    "grid_t10",
    "grid_t5",
    "grid_t1",
    "grid_t0",
    "drop_t10",
    "drop_t5",
    "drop_t1",
    "drop_t0",
    "brown_t10",
    "brown_t5",
    "brown_t1",
    "brown_t0",
    "is_brown_grid",
    "brown_at",
]


def pivot_odds(rows: list[dict], threshold: float = 50.0, pool: str = "win") -> list[dict]:
    """One row per horse. pool='win' uses win_odds; pool='place' uses place_odds."""
    field = "place_odds" if pool == "place" else "win_odds"
    grid_field = "place_grid" if pool == "place" else "hkjc_grid"
    pool_label = "PLA" if pool == "place" else "WIN"
    grouped: dict[tuple, dict] = {}
    for row in rows:
        cp = str(row.get("checkpoint") or "")
        if cp not in CP_SUFFIX:
            continue
        key = (
            str(row.get("race_date", "")),
            str(row.get("venue", "")),
            str(row.get("race_no", "")),
            str(row.get("horse_no", "")),
        )
        item = grouped.setdefault(
            key,
            {
                "race_date": row.get("race_date", ""),
                "venue": row.get("venue", ""),
                "race_no": row.get("race_no", ""),
                "scheduled_time": row.get("scheduled_time", ""),
                "horse_no": row.get("horse_no", ""),
                "horse_name": row.get("horse_name", ""),
                "odds": {},
                "grids": {},
            },
        )
        if row.get("horse_name"):
            item["horse_name"] = row.get("horse_name")
        if row.get("scheduled_time"):
            item["scheduled_time"] = row.get("scheduled_time")
        item["odds"][cp] = parse_odds(row.get(field))
        item["grids"][cp] = parse_hkjc_grid(row.get(grid_field))

    wide: list[dict] = []
    for item in grouped.values():
        out = {
            "pool": pool_label,
            "race_date": item["race_date"],
            "venue": item["venue"],
            "race_no": item["race_no"],
            "scheduled_time": item["scheduled_time"],
            "horse_no": item["horse_no"],
            "horse_name": item["horse_name"],
        }
        brown_at: list[str] = []
        prev_cp = None
        for cp in CHECKPOINTS:
            suffix = CP_SUFFIX[cp]
            current = item["odds"].get(cp)
            grid = item["grids"].get(cp) or ""
            out[f"odds_{suffix}"] = "" if current is None else current
            out[f"grid_{suffix}"] = grid
            if prev_cp is None:
                brown = grid == "brown"
                if brown:
                    brown_at.append(cp)
                prev_cp = cp
                continue
            prev = item["odds"].get(prev_cp)
            drop = win_drop_pct(prev, current)
            brown = official_brown(grid, drop, threshold)
            out[f"drop_{suffix}"] = drop
            out[f"brown_{suffix}"] = "true" if brown else "false"
            if brown:
                brown_at.append(cp)
            prev_cp = cp
        out["is_brown_grid"] = "true" if brown_at else "false"
        out["brown_at"] = "、".join(brown_at)
        wide.append(out)

    wide.sort(
        key=lambda r: (
            str(r["race_date"]),
            str(r["venue"]),
            int(float(r["race_no"] or 0)),
            int(float(r["horse_no"] or 0)),
        )
    )
    return wide
