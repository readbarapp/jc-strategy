from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.backtest import evaluate
from src.csv_store import load_odds, load_results
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
    stats = evaluate(odds, results, min_odds=3.5, max_odds=9.0, bet_type="win", stake=10, threshold=50)
    assert "roi" in stats
    assert stats["triggers"] > 20
    assert stats["staked"] == stats["triggers"] * 10
    brown = sum(1 for r in odds if str(r["is_brown_grid"]).lower() == "true")
    assert brown > 30


if __name__ == "__main__":
    test_timezone_is_hong_kong()
    test_drop_and_brown_grid()
    test_checkpoints()
    test_backtest_on_sample()
    print("all tests ok")
