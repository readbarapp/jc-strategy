from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.backtest import evaluate, payout_odds, race_day_count, scale_unit_pnl, ticket_pnl, trigger_rows, yearly_bets
from src.csv_store import load_odds, load_results
from src.hkjc_client import HKJCClient, Meeting
from src.monitor import plan_auto, restore_monitor_state, should_handoff
from src.odds_board import pivot_odds
from src.odds_math import is_brown_grid, match_checkpoint, parse_odds, win_drop_pct
from src.telegram_notify import format_alert, should_alert
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
    assert match_checkpoint(3) is None  # T-3 is not captured; gap between T-5 and T-1
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
    days = race_day_count(odds)
    assert days >= 1
    assert stats["race_days"] == days
    assert stats["triggers_per_race_day"] == round(stats["triggers"] / days, 2)


def test_strategy_filter_matches_backtest_triggers():
    """Data-center 「只看符合策略」 uses the same horse set as strategy-tab trigger_rows."""
    odds = load_odds()
    results = load_results()
    trigs = trigger_rows(odds, 3.5, 9.0, 50, "T-1")
    assert trigs, "sample data should have at least one strategy match"
    keys = {
        (r["race_date"], r["venue"], str(r["race_no"]), str(r["horse_no"]))
        for r in trigs
    }
    for row in trigs:
        assert str(row.get("checkpoint")) == "T-1"
        win = float(row["win_odds"])
        assert 3.5 <= win <= 9.0
        drop = float(row.get("win_drop_pct") or 0)
        brown = str(row.get("is_brown_grid")).lower() == "true" or drop >= 50
        assert brown
    stats = evaluate(
        odds, results, min_odds=3.5, max_odds=9.0, bet_type="win", stake=10, threshold=50, checkpoint="T-1"
    )
    trade_keys = {
        (t["race_date"], t["venue"], str(t["race_no"]), str(t["horse_no"]))
        for t in stats["trades"]
    }
    assert trade_keys <= keys
    place_stats = evaluate(
        odds, results, min_odds=3.5, max_odds=9.0, bet_type="place", stake=10, threshold=50, checkpoint="T-1"
    )
    place_keys = {
        (t["race_date"], t["venue"], str(t["race_no"]), str(t["horse_no"]))
        for t in place_stats["trades"]
    }
    assert place_keys == trade_keys
    board = pivot_odds(odds, 50, pool="win")
    matched = [
        r
        for r in board
        if (r["race_date"], r["venue"], str(r["race_no"]), str(r["horse_no"])) in keys
    ]
    assert len(matched) == len(keys)
    wider = trigger_rows(odds, 1.1, 50.0, 50, "T-1")
    assert len(wider) >= len(trigs)


def test_odds_board_one_row_per_horse():
    odds = load_odds()
    board = pivot_odds(odds, 50, pool="win")
    keys = {(r["race_date"], r["venue"], str(r["race_no"]), str(r["horse_no"])) for r in odds}
    assert len(board) == len(keys)
    sample = next(r for r in board if r["is_brown_grid"] == "true")
    assert sample["brown_at"]
    assert sample["pool"] == "WIN"
    assert sample["odds_t15"] != "" or sample["odds_t10"] != ""
    assert "odds_t3" not in sample


def test_t1_brown_compares_to_t5_not_t3():
    """T-1 啡格 uses T-5 odds even if a leftover T-3 snapshot exists."""
    rows = [
        {
            "race_date": "2026-11-15",
            "venue": "ST",
            "race_no": "1",
            "horse_no": "7",
            "horse_name": "和諧王",
            "scheduled_time": "15:20:00",
            "checkpoint": "T-5",
            "win_odds": 10.0,
            "place_odds": 3.0,
        },
        {
            "race_date": "2026-11-15",
            "venue": "ST",
            "race_no": "1",
            "horse_no": "7",
            "horse_name": "和諧王",
            "scheduled_time": "15:20:00",
            "checkpoint": "T-3",
            "win_odds": 9.8,
            "place_odds": 2.9,
        },
        {
            "race_date": "2026-11-15",
            "venue": "ST",
            "race_no": "1",
            "horse_no": "7",
            "horse_name": "和諧王",
            "scheduled_time": "15:20:00",
            "checkpoint": "T-1",
            "win_odds": 4.5,
            "place_odds": 1.6,
        },
    ]
    board = pivot_odds(rows, 50, pool="win")
    assert len(board) == 1
    row = board[0]
    assert row["odds_t5"] == 10.0
    assert row["odds_t1"] == 4.5
    assert "odds_t3" not in row
    assert row["brown_t1"] == "true"
    assert "T-1" in row["brown_at"]
    # 10.0 → 4.5 is 55%; 9.8 → 4.5 would also brown, but we must use T-5
    assert abs(float(row["drop_t1"]) - 55.0) < 0.01


def test_win_and_place_boards_are_separate():
    odds = load_odds()
    win_board = pivot_odds(odds, 50, pool="win")
    place_board = pivot_odds(odds, 50, pool="place")
    assert len(win_board) == len(place_board)
    assert all(r["pool"] == "WIN" for r in win_board)
    assert all(r["pool"] == "PLA" for r in place_board)
    differed = False
    for w, p in zip(win_board, place_board):
        assert (w["race_date"], w["horse_no"]) == (p["race_date"], p["horse_no"])
        if w["odds_t1"] != "" and p["odds_t1"] != "" and float(w["odds_t1"]) != float(p["odds_t1"]):
            differed = True
            break
    assert differed, "place odds must not be a copy of win odds"


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


def test_place_and_win_place_use_official_dividends_not_win_odds():
    odds = [
        {
            "race_date": "2026-11-15",
            "venue": "ST",
            "race_no": "1",
            "checkpoint": "T-1",
            "horse_no": "3",
            "horse_name": "金程千里",
            "win_odds": 6.0,
            "place_odds": 1.8,
            "win_drop_pct": 55,
            "is_brown_grid": "true",
        }
    ]
    results = [
        {
            "race_date": "2026-11-15",
            "venue": "ST",
            "race_no": "1",
            "horse_no": "3",
            "finish_rank": 2,
            "win_dividend": 0,
            "placedividend": 22.0,
        }
    ]
    place = evaluate(odds, results, bet_type="place", checkpoint="T-1", threshold=50)
    assert place["triggers"] == 1
    assert place["pnl"] == 12.0  # 22 - 10; never uses 6.0 win odds
    win_only = evaluate(odds, results, bet_type="win", checkpoint="T-1", threshold=50)
    assert win_only["pnl"] == -10.0
    both = evaluate(odds, results, bet_type="win_place", checkpoint="T-1", threshold=50)
    assert both["staked"] == 20
    assert both["pnl"] == 2.0  # -10 win + 12 place
    big_place = evaluate(odds, results, bet_type="place", checkpoint="T-1", threshold=50, stake=10000)
    assert big_place["pnl"] == 12000
    assert big_place["roi"] == place["roi"]
    assert big_place["avg_payout_odds"] == place["avg_payout_odds"] == 2.2


def test_winplaodds_string_keeps_pools_apart():
    win_map: dict[int, float | None] = {}
    pla_map: dict[int, float | None] = {}
    text = "WIN;1=8.4=0;2=3.5=0#PLA;1=2.1=0;2=1.4=0"
    win_part, _, pla_part = text.partition("#")
    HKJCClient._parse_pool_segment(win_part, win_map)
    HKJCClient._parse_pool_segment(pla_part, pla_map)
    assert win_map == {1: 8.4, 2: 3.5}
    assert pla_map == {1: 2.1, 2: 1.4}


def test_telegram_uses_own_checkpoint_odds_and_bet_label():
    cfg = {
        "telegram": {
            "enabled": True,
            "bot_token": "x",
            "chat_id": "1",
            "bet_type": "place",
            "checkpoint": "T-1",
            "min_odds": 3.5,
            "max_odds": 9.0,
            "min_drop_pct": 50,
        }
    }
    hit = {
        "checkpoint": "T-1",
        "win_odds": 4.2,
        "place_odds": 1.7,
        "win_drop_pct": 55,
        "is_brown_grid": "true",
        "venue": "ST",
        "race_no": 5,
        "horse_no": 7,
        "horse_name": "金程千里",
        "prev_win_odds": 9.4,
        "race_date": "2026-11-15",
        "scheduled_time": "15:20:00",
        "capture_timestamp": "2026-11-15 15:19:00",
    }
    miss_cp = dict(hit, checkpoint="T-5")
    miss_odds = dict(hit, win_odds=12.0)
    assert should_alert(cfg, hit) is True
    assert should_alert(cfg, miss_cp) is False
    assert should_alert(cfg, miss_odds) is False
    text = format_alert(cfg, hit)
    assert "只買位置" in text
    assert "T-1" in text
    assert "4.2" in text
    assert "1.7" in text


def test_plan_auto_uses_actual_post_times():
    first = parse_hk("2026-11-18 12:45:00")
    last = parse_hk("2026-11-18 17:15:00")
    posts = [first, last]
    far = plan_auto(parse_hk("2026-11-18 10:00:00"), posts, max_wait_minutes=45)
    assert far.action == "defer"
    assert far.wait_minutes > 45
    near = plan_auto(parse_hk("2026-11-18 12:20:00"), posts, max_wait_minutes=45)
    assert near.action == "monitor"
    during = plan_auto(parse_hk("2026-11-18 13:00:00"), posts)
    assert during.action == "monitor"
    after = plan_auto(parse_hk("2026-11-18 18:00:00"), posts, trail_minutes=25)
    assert after.action == "results"
    unknown = plan_auto(parse_hk("2026-11-18 10:00:00"), [])
    assert unknown.action == "monitor"
    hv_first = parse_hk("2026-11-18 19:15:00")
    hv = plan_auto(
        parse_hk("2026-11-18 17:30:00"),
        [hv_first, parse_hk("2026-11-18 23:10:00")],
        max_wait_minutes=45,
    )
    assert hv.action == "defer"
    hv_near = plan_auto(
        parse_hk("2026-11-18 18:20:00"),
        [hv_first, parse_hk("2026-11-18 23:10:00")],
        max_wait_minutes=45,
    )
    assert hv_near.action == "monitor"


def test_ticket_pnl_scales_hkjc_ten_dollar_unit():
    assert ticket_pnl(60, 10) == 50
    assert ticket_pnl(60, 10000) == 50000
    assert ticket_pnl(0, 10) == -10
    assert ticket_pnl(0, 10000) == -10000
    assert payout_odds(60) == 6.0
    assert payout_odds(22) == 2.2
    assert scale_unit_pnl(-10, 10000) == -10000
    assert scale_unit_pnl(42, 10000) == 42000
    small = evaluate(
        [
            {
                "race_date": "2026-11-15",
                "venue": "ST",
                "race_no": "1",
                "checkpoint": "T-1",
                "horse_no": "3",
                "win_odds": 6.0,
                "win_drop_pct": 55,
                "is_brown_grid": "true",
            }
        ],
        [
            {
                "race_date": "2026-11-15",
                "venue": "ST",
                "race_no": "1",
                "horse_no": "3",
                "finish_rank": 1,
                "win_dividend": 60,
                "placedividend": 20,
            }
        ],
        bet_type="win",
        checkpoint="T-1",
        threshold=50,
        stake=10,
    )
    big = evaluate(
        [
            {
                "race_date": "2026-11-15",
                "venue": "ST",
                "race_no": "1",
                "checkpoint": "T-1",
                "horse_no": "3",
                "win_odds": 6.0,
                "win_drop_pct": 55,
                "is_brown_grid": "true",
            }
        ],
        [
            {
                "race_date": "2026-11-15",
                "venue": "ST",
                "race_no": "1",
                "horse_no": "3",
                "finish_rank": 1,
                "win_dividend": 60,
                "placedividend": 20,
            }
        ],
        bet_type="win",
        checkpoint="T-1",
        threshold=50,
        stake=10000,
    )
    assert small["pnl"] == 50
    assert big["pnl"] == 50000
    assert big["roi"] == small["roi"] == 500.0


def test_yearly_bets_is_frequency_times_race_days():
    assert yearly_bets(2.5, 88) == 220
    assert yearly_bets(3.2, 88) == 282
    assert yearly_bets(0, 88) == 0
    odds = load_odds()
    results = load_results()
    stats = evaluate(
        odds, results, min_odds=3.5, max_odds=9.0, bet_type="win", stake=10, threshold=50, checkpoint="T-1"
    )
    expected = round(stats["triggers_per_race_day"] * 88)
    assert yearly_bets(stats["triggers_per_race_day"], 88) == expected


def test_first_live_upsert_drops_demo_rows():
    import shutil
    import tempfile

    import src.csv_store as cs
    from src.schema import ODDS_FIELDS

    original = {
        "DATA_DIR": cs.DATA_DIR,
        "DOCS_DATA": cs.DOCS_DATA,
        "ODDS_PATH": cs.ODDS_PATH,
        "RESULTS_PATH": cs.RESULTS_PATH,
        "BOARD_PATH": cs.BOARD_PATH,
        "WIN_BOARD_PATH": cs.WIN_BOARD_PATH,
        "PLACE_BOARD_PATH": cs.PLACE_BOARD_PATH,
        "ORIGIN_PATH": cs.ORIGIN_PATH,
        "DOCS_ORIGIN_PATH": cs.DOCS_ORIGIN_PATH,
    }
    root = Path(tempfile.mkdtemp())
    try:
        cs.DATA_DIR = root
        cs.DOCS_DATA = root / "docs"
        cs.ODDS_PATH = root / "odds_snapshots.csv"
        cs.RESULTS_PATH = root / "race_results.csv"
        cs.BOARD_PATH = root / "odds_board.csv"
        cs.WIN_BOARD_PATH = root / "win_board.csv"
        cs.PLACE_BOARD_PATH = root / "place_board.csv"
        cs.ORIGIN_PATH = root / "dataset_origin.json"
        cs.DOCS_ORIGIN_PATH = root / "docs" / "dataset_origin.json"
        cs.write_rows(
            cs.ODDS_PATH,
            ODDS_FIELDS,
            [
                {
                    "race_date": "2026-10-15",
                    "venue": "HV",
                    "race_no": "1",
                    "scheduled_time": "19:15:00",
                    "checkpoint": "T-1",
                    "capture_timestamp": "2026-10-15 19:14:00",
                    "horse_no": "1",
                    "horse_name": "示範馬",
                    "win_odds": "4.0",
                    "place_odds": "1.7",
                    "prev_win_odds": "8.0",
                    "win_drop_pct": "50.0",
                    "is_brown_grid": "true",
                }
            ],
        )
        cs.set_dataset_origin("demo", "test")
        assert cs.dataset_origin() == "demo"
        cs.upsert_odds(
            [
                {
                    "race_date": "2026-11-18",
                    "venue": "HV",
                    "race_no": "3",
                    "scheduled_time": "19:45:00",
                    "checkpoint": "T-1",
                    "capture_timestamp": "2026-11-18 19:44:00",
                    "horse_no": "7",
                    "horse_name": "金程千里",
                    "win_odds": "5.2",
                    "place_odds": "2.0",
                    "prev_win_odds": "11.0",
                    "win_drop_pct": "52.7",
                    "is_brown_grid": "true",
                }
            ]
        )
        rows = cs.load_odds()
        assert len(rows) == 1
        assert rows[0]["race_date"] == "2026-11-18"
        assert rows[0]["horse_name"] == "金程千里"
        assert cs.dataset_origin() == "live"
    finally:
        for key, value in original.items():
            setattr(cs, key, value)
        shutil.rmtree(root, ignore_errors=True)


def test_restore_monitor_state_and_handoff_budget():
    meeting = Meeting(race_date="2026-11-15", venue="ST")
    odds_map, captured, alerted = restore_monitor_state(meeting)
    assert captured
    assert any(ck == "T-1" for _, _, ck in captured)
    assert odds_map
    assert alerted == set()
    assert should_handoff(100, 19800) is False
    assert should_handoff(19800, 19800) is True
    client = HKJCClient()
    assert client.recommended_sleep(10) == 10
    client.consecutive_blocks = 2
    assert client.recommended_sleep(10) == 30


if __name__ == "__main__":
    test_timezone_is_hong_kong()
    test_drop_and_brown_grid()
    test_checkpoints()
    test_backtest_on_sample()
    test_odds_board_one_row_per_horse()
    test_t1_brown_compares_to_t5_not_t3()
    test_win_and_place_boards_are_separate()
    test_t1_strategy_ignores_other_checkpoints()
    test_place_and_win_place_use_official_dividends_not_win_odds()
    test_ticket_pnl_scales_hkjc_ten_dollar_unit()
    test_winplaodds_string_keeps_pools_apart()
    test_telegram_uses_own_checkpoint_odds_and_bet_label()
    test_plan_auto_uses_actual_post_times()
    test_yearly_bets_is_frequency_times_race_days()
    test_first_live_upsert_drops_demo_rows()
    test_restore_monitor_state_and_handoff_budget()
    print("all tests ok")
