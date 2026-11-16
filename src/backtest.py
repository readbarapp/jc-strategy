"""Python backtest used by self-check; the live dashboard recomputes in JS."""

from __future__ import annotations

from typing import Iterable

from .odds_math import parse_odds


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _place_ok(rank: int, field_size: int) -> bool:
    if rank <= 0:
        return False
    if field_size <= 3:
        return rank == 1
    if field_size <= 6:
        return rank <= 2
    return rank <= 3


def trigger_rows(
    odds: Iterable[dict],
    min_odds: float,
    max_odds: float,
    threshold: float,
    checkpoint: str = "T-1",
) -> list[dict]:
    """Bet only if 啡格 appears at the chosen checkpoint and that tick's odds are in range."""
    wanted = (checkpoint or "T-1").strip().upper()
    if wanted.isdigit():
        wanted = f"T-{wanted}"
    best: dict[tuple, dict] = {}
    for row in odds:
        if str(row.get("checkpoint") or "").upper() != wanted:
            continue
        win = parse_odds(row.get("win_odds"))
        drop = float(row.get("win_drop_pct") or 0)
        brown = _truthy(row.get("is_brown_grid")) or drop >= threshold
        if win is None or not brown:
            continue
        if not (min_odds <= win <= max_odds):
            continue
        key = (row.get("race_date"), row.get("venue"), str(row.get("race_no")), str(row.get("horse_no")))
        item = dict(row)
        item["win_odds"] = win
        best[key] = item
    return list(best.values())


def evaluate(
    odds: list[dict],
    results: list[dict],
    min_odds: float = 3.5,
    max_odds: float = 9.0,
    bet_type: str = "win",
    stake: float = 10.0,
    threshold: float = 50.0,
    checkpoint: str = "T-1",
) -> dict:
    result_map = {
        (r["race_date"], r["venue"], str(r["race_no"]), str(r["horse_no"])): r
        for r in results
    }
    field_sizes: dict[tuple, int] = {}
    for r in results:
        key = (r["race_date"], r["venue"], str(r["race_no"]))
        field_sizes[key] = field_sizes.get(key, 0) + 1

    trades = []
    for trig in trigger_rows(odds, min_odds, max_odds, threshold, checkpoint):
        key = (trig["race_date"], trig["venue"], str(trig["race_no"]), str(trig["horse_no"]))
        res = result_map.get(key)
        if not res:
            continue
        rank = int(float(res.get("finish_rank") or 0))
        win_div = float(res.get("win_dividend") or 0)
        pla_div = float(res.get("placedividend") or 0)
        field = field_sizes.get((trig["race_date"], trig["venue"], str(trig["race_no"])), 14)
        pnl = 0.0
        hit = False
        payout_odds = 0.0
        if bet_type in {"win", "win_place"}:
            pnl += (win_div - stake) if win_div > 0 else -stake
            if win_div > 0:
                hit = True
                payout_odds = win_div / stake
        if bet_type in {"place", "win_place"}:
            placed = pla_div > 0 or _place_ok(rank, field)
            got = pla_div if pla_div > 0 else 0.0
            pnl += (got - stake) if got > 0 else -stake
            if got > 0:
                hit = True
                payout_odds = max(payout_odds, got / stake)
        stakes = stake * (2 if bet_type == "win_place" else 1)
        trades.append({**trig, "pnl": round(pnl, 2), "hit": hit, "payout_odds": payout_odds, "stakes": stakes})

    n = len(trades)
    hits = sum(1 for t in trades if t["hit"])
    staked = sum(t["stakes"] for t in trades)
    pnl = sum(t["pnl"] for t in trades)
    win_rate = (hits / n * 100.0) if n else 0.0
    avg_payout = (
        sum(t["payout_odds"] for t in trades if t["hit"]) / hits if hits else 0.0
    )
    roi = (pnl / staked * 100.0) if staked else 0.0
    return {
        "triggers": n,
        "hits": hits,
        "win_rate": round(win_rate, 2),
        "avg_payout_odds": round(avg_payout, 2),
        "staked": round(staked, 2),
        "pnl": round(pnl, 2),
        "roi": round(roi, 2),
        "trades": trades,
    }
