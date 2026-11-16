from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.backtest import evaluate
from src.csv_store import load_odds, load_results
from src.odds_board import pivot_odds
from src.odds_math import is_brown_grid, match_checkpoint, parse_odds, win_drop_pct
from src.timeutil import HK_TZ, format_hk, parse_hk


def test_timezone_is_hong_kong():
    dt = parse_hk("2026-11-16 15:30:00")
    assert str(dt.tzinfo) == "Asia/Hong_Kong" or dt.tzinfo == HK_TZ
    assert dt.utcoffset().total_seconds() == 8 * 3600
    assert format_hk(dt) == "2026-11-16 15:30:00"


def test_drop_and_brown_grid():
    assert win_drop_pct(8.0, 4.0) == 50.0
    assert is_brown_grid(50, 50) is True
    assert is_brown_grid(49.9, 50) is False
    assert parse_odds("SCR") is None
    assert parse_odds("3.5") == 3.5


def test_checkpoints():
    assert match_checkpoint(15) == "T-15"
    assert match_checkpoint(10) == "T-10"
    assert match_checkpoint(5) == "T-5"
    assert match_checkpoint(3) == "T-3"
    assert match_checkpoint(1) == "T-1"
    assert match_checkpoint(0) == "T-0"
    assert match_checkpoint(40) is None


def test_backtest_on_sample():
    odds = load_odds()
    results = load_results()
    assert len(odds) > 100
    assert len(results) > 50
    stats = evaluate(
        odds, results, min_odds=3.5, max_odds=9.0, bet_type="win", stake=10, threshold=50, checkpoint="T-1"
    )
    assert "roi" in stats
    assert stats["triggers"] >= 1
    assert stats["staked"] == stats["triggers"] * 10
    assert all(str(t.get("checkpoint")) == "T-1" for t in stats["trades"])
    brown = sum(1 for r in odds if str(r["is_brown_grid"]).lower() == "true")
    assert brown > 30
    names = {r["horse_name"] for r in odds}
    assert any(any("\u4e00" <= ch <= "\u9fff" for ch in name) for name in names)


def test_odds_board_one_row_per_horse():
    odds = load_odds()
    board = pivot_odds(odds, 50)
    keys = {(r["race_date"], r["venue"], str(r["race_no"]), str(r["horse_no"])) for r in odds}
    assert len(board) == len(keys)
    sample = next(r for r in board if r["is_brown_grid"] == "true")
    assert sample["brown_at"]
    assert sample["win_t15"] != "" or sample["win_t10"] != ""


def test_t1_strategy_ignores_other_checkpoints():
    odds = [
        {
            "race_date": "2026-11-15",
            "venue": "ST",
            "race_no": "1",
            "checkpoint": "T-5",
            "horse_no": "7",
            "horse_name": "和諧王",
            "win_odds": 4.0,
            "win_drop_pct": 60,
            "is_brown_grid": "true",
        },
        {
            "race_date": "2026-11-15",
            "venue": "ST",
            "race_no": "1",
            "checkpoint": "T-1",
            "horse_no": "7",
            "horse_name": "和諧王",
            "win_odds": 5.0,
            "win_drop_pct": 10,
            "is_brown_grid": "false",
        },
        {
            "race_date": "2026-11-15",
            "venue": "ST",
            "race_no": "2",
            "checkpoint": "T-1",
            "horse_no": "3",
            "horse_name": "金程千里",
            "win_odds": 6.0,
            "win_drop_pct": 55,
            "is_brown_grid": "true",
        },
    ]
    results = [
        {
            "race_date": "2026-11-15",
            "venue": "ST",
            "race_no": "1",
            "horse_no": "7",
            "finish_rank": 4,
            "win_dividend": 0,
            "placedividend": 0,
        },
        {
            "race_date": "2026-11-15",
            "venue": "ST",
            "race_no": "2",
            "horse_no": "3",
            "finish_rank": 1,
            "win_dividend": 60,
            "placedividend": 20,
        },
    ]
    stats = evaluate(odds, results, min_odds=3.5, max_odds=9.0, checkpoint="T-1", threshold=50)
    assert stats["triggers"] == 1
    assert stats["trades"][0]["horse_no"] == "3"


if __name__ == "__main__":
    test_timezone_is_hong_kong()
    test_drop_and_brown_grid()
    test_checkpoints()
    test_backtest_on_sample()
    test_odds_board_one_row_per_horse()
    test_t1_strategy_ignores_other_checkpoints()
    print("all tests ok")
