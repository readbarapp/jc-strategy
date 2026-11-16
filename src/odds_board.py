"""Pivot checkpoint snapshots into one row per horse."""

from __future__ import annotations

from .odds_math import is_brown_grid, parse_odds, win_drop_pct

CHECKPOINTS = ["T-15", "T-10", "T-5", "T-3", "T-1", "T-0"]
CP_SUFFIX = {
    "T-15": "t15",
    "T-10": "t10",
    "T-5": "t5",
    "T-3": "t3",
    "T-1": "t1",
    "T-0": "t0",
}
WIDE_FIELDS = [
    "race_date",
    "venue",
    "race_no",
    "scheduled_time",
    "horse_no",
    "horse_name",
    "win_t15",
    "win_t10",
    "win_t5",
    "win_t3",
    "win_t1",
    "win_t0",
    "drop_t10",
    "drop_t5",
    "drop_t3",
    "drop_t1",
    "drop_t0",
    "brown_t10",
    "brown_t5",
    "brown_t3",
    "brown_t1",
    "brown_t0",
    "is_brown_grid",
    "brown_at",
]
WIDE_EXPORT_HEADERS = [
    "日期",
    "場地",
    "場次",
    "開跑時間",
    "馬號",
    "馬名",
    "開賽前15分鐘",
    "開賽前10分鐘",
    "開賽前5分鐘",
    "開賽前3分鐘",
    "開賽前1分鐘",
    "開跑",
    "T-10跌幅%",
    "T-5跌幅%",
    "T-3跌幅%",
    "T-1跌幅%",
    "開跑跌幅%",
    "T-10啡格",
    "T-5啡格",
    "T-3啡格",
    "T-1啡格",
    "開跑啡格",
    "是否啡格",
    "啡格時間點",
]


def pivot_odds(rows: list[dict], threshold: float = 50.0) -> list[dict]:
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
            },
        )
        if row.get("horse_name"):
            item["horse_name"] = row.get("horse_name")
        if row.get("scheduled_time"):
            item["scheduled_time"] = row.get("scheduled_time")
        item["odds"][cp] = parse_odds(row.get("win_odds"))

    wide: list[dict] = []
    for item in grouped.values():
        out = {
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
            out[f"win_{suffix}"] = "" if current is None else current
            if prev_cp is None:
                prev_cp = cp
                continue
            prev = item["odds"].get(prev_cp)
            drop = win_drop_pct(prev, current)
            brown = is_brown_grid(drop, threshold) if current is not None and prev is not None else False
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
