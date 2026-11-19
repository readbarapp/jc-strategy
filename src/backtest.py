"""Python backtest used by self-check; the live dashboard recomputes in JS."""

from __future__ import annotations

from typing import Iterable

from .odds_math import official_brown, parse_odds

DEFAULT_RACE_DAYS_PER_YEAR = 88
HKJC_TICKET_UNIT = 10.0  # official win/place dividends are per $10 ticket


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
        brown = official_brown(row.get("hkjc_grid"), drop, threshold, row.get("is_brown_grid"))
        if win is None or not brown:
            continue
        if not (min_odds <= win <= max_odds):
            continue
        key = (row.get("race_date"), row.get("venue"), str(row.get("race_no")), str(row.get("horse_no")))
        item = dict(row)
        item["win_odds"] = win
        best[key] = item
    return list(best.values())


def ticket_pnl(dividend: float, stake: float, unit: float = HKJC_TICKET_UNIT) -> float:
    """Net PnL for one HKJC ticket.

    Official dividends are the return on a $10 ticket (stake included).
    A $10,000 stake is 1,000 such tickets: pnl = (dividend - 10) * (stake / 10).
    """
    unit = float(unit or HKJC_TICKET_UNIT)
    stake = float(stake)
    if unit <= 0 or stake == 0:
        return 0.0
    div = float(dividend or 0)
    if div > 0:
        return div * (stake / unit) - stake
    return -stake


def payout_odds(dividend: float, unit: float = HKJC_TICKET_UNIT) -> float:
    """Decimal odds including stake, from an official per-$10 dividend."""
    unit = float(unit or HKJC_TICKET_UNIT)
    div = float(dividend or 0)
    if div <= 0 or unit <= 0:
        return 0.0
    return div / unit


def scale_unit_pnl(pnl: float, stake: float, unit: float = HKJC_TICKET_UNIT) -> float:
    """Lift a $10-ticket historical PnL onto another stake size."""
    unit = float(unit or HKJC_TICKET_UNIT)
    if unit <= 0:
        return float(pnl)
    return float(pnl) * (float(stake) / unit)


def yearly_bets(
    triggers_per_race_day: float,
    race_days_per_year: float = DEFAULT_RACE_DAYS_PER_YEAR,
) -> int:
    """Expected bets in a HKJC season: strategy frequency × race days per year."""
    days = max(1, int(race_days_per_year or DEFAULT_RACE_DAYS_PER_YEAR))
    freq = float(triggers_per_race_day or 0)
    return max(0, int(round(freq * days)))


def race_day_count(rows: Iterable[dict]) -> int:
    """Unique (race_date, venue) days in the odds/results sample — including days with 0 trades."""
    keys = {
        (str(r.get("race_date") or ""), str(r.get("venue") or ""))
        for r in rows
        if r.get("race_date")
    }
    return len(keys)


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

    trades = []
    for trig in trigger_rows(odds, min_odds, max_odds, threshold, checkpoint):
        key = (trig["race_date"], trig["venue"], str(trig["race_no"]), str(trig["horse_no"]))
        res = result_map.get(key)
        if not res:
            continue
        rank = int(float(res.get("finish_rank") or 0))
        win_div = float(res.get("win_dividend") or 0)
        pla_div = float(res.get("placedividend") or 0)
        pnl = 0.0
        hit = False
        pay_odds = 0.0
        if bet_type in {"win", "win_place"}:
            pnl += ticket_pnl(win_div, stake)
            if win_div > 0:
                hit = True
                pay_odds = payout_odds(win_div)
        if bet_type in {"place", "win_place"}:
            # Official placedividend only — do not invent place pay from win odds or rank.
            pnl += ticket_pnl(pla_div, stake)
            if pla_div > 0:
                hit = True
                pay_odds = max(pay_odds, payout_odds(pla_div))
        stakes = stake * (2 if bet_type == "win_place" else 1)
        trades.append(
            {
                **trig,
                "pnl": round(pnl, 2),
                "hit": hit,
                "payout_odds": pay_odds,
                "stakes": stakes,
                "finish_rank": rank,
            }
        )

    n = len(trades)
    hits = sum(1 for t in trades if t["hit"])
    staked = sum(t["stakes"] for t in trades)
    pnl = sum(t["pnl"] for t in trades)
    win_rate = (hits / n * 100.0) if n else 0.0
    avg_payout = (
        sum(t["payout_odds"] for t in trades if t["hit"]) / hits if hits else 0.0
    )
    roi = (pnl / staked * 100.0) if staked else 0.0
    race_days = race_day_count(odds)
    per_day = (n / race_days) if race_days else 0.0
    return {
        "triggers": n,
        "hits": hits,
        "win_rate": round(win_rate, 2),
        "avg_payout_odds": round(avg_payout, 2),
        "staked": round(staked, 2),
        "pnl": round(pnl, 2),
        "roi": round(roi, 2),
        "race_days": race_days,
        "triggers_per_race_day": round(per_day, 2),
        "trades": trades,
    }
