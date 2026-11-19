"""Append / upsert CSV tables used by the Pages frontend."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .logger import log
from .odds_board import WIDE_FIELDS, pivot_odds
from .odds_math import GRID_BROWN, official_brown, parse_odds, stored_grid, win_drop_pct
from .schema import ODDS_FIELDS, RESULTS_FIELDS, TICK_FIELDS
from .timeutil import iso_hk, now_hk

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DOCS_DATA = ROOT / "docs" / "data"
ODDS_PATH = DATA_DIR / "odds_snapshots.csv"
RESULTS_PATH = DATA_DIR / "race_results.csv"
TICK_PATH = DATA_DIR / "odds_ticks.csv"
BOARD_PATH = DATA_DIR / "odds_board.csv"
WIN_BOARD_PATH = DATA_DIR / "win_board.csv"
PLACE_BOARD_PATH = DATA_DIR / "place_board.csv"
ORIGIN_PATH = DATA_DIR / "dataset_origin.json"
DOCS_ORIGIN_PATH = DOCS_DATA / "dataset_origin.json"
def inbox_dir() -> Path:
    return DATA_DIR / "live_inbox"


def inbox_odds_path() -> Path:
    return inbox_dir() / "odds_snapshots.csv"


def inbox_results_path() -> Path:
    return inbox_dir() / "race_results.csv"


def inbox_ticks_path() -> Path:
    return inbox_dir() / "odds_ticks.csv"


def _ensure(path: Path, fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=fields).writeheader()


def read_rows(path: Path, fields: list[str]) -> list[dict]:
    _ensure(path, fields)
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [{k: (row.get(k) or "") for k in fields} for row in csv.DictReader(handle)]


def write_rows(path: Path, fields: list[str], rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def _key_odds(row: dict) -> tuple:
    return (
        str(row.get("race_date", "")),
        str(row.get("venue", "")),
        str(row.get("race_no", "")),
        str(row.get("checkpoint", "")),
        str(row.get("horse_no", "")),
    )


def _key_result(row: dict) -> tuple:
    return (
        str(row.get("race_date", "")),
        str(row.get("venue", "")),
        str(row.get("race_no", "")),
        str(row.get("horse_no", "")),
    )


def _key_tick(row: dict) -> tuple:
    return (
        str(row.get("race_date", "")),
        str(row.get("venue", "")),
        str(row.get("race_no", "")),
        str(row.get("horse_no", "")),
        str(row.get("capture_timestamp", "")),
    )


def upsert(path: Path, fields: list[str], incoming: list[dict], key_fn) -> int:
    existing = read_rows(path, fields)
    index = {key_fn(row): i for i, row in enumerate(existing)}
    added = 0
    for row in incoming:
        clean = {k: row.get(k, "") for k in fields}
        key = key_fn(clean)
        if key in index:
            existing[index[key]] = clean
        else:
            index[key] = len(existing)
            existing.append(clean)
            added += 1
    write_rows(path, fields, existing)
    return added


def rebuild_odds_board(threshold: float = 50.0) -> None:
    snapshots = load_odds()
    win_rows = pivot_odds(snapshots, threshold, pool="win")
    place_rows = pivot_odds(snapshots, threshold, pool="place")
    write_rows(WIN_BOARD_PATH, WIDE_FIELDS, win_rows)
    write_rows(PLACE_BOARD_PATH, WIDE_FIELDS, place_rows)
    write_rows(BOARD_PATH, WIDE_FIELDS, win_rows)


def dataset_origin() -> str:
    if ORIGIN_PATH.exists():
        try:
            payload = json.loads(ORIGIN_PATH.read_text(encoding="utf-8"))
            origin = str(payload.get("origin") or "").strip().lower()
            if origin in {"demo", "live", "empty"}:
                return origin
        except json.JSONDecodeError:
            pass
    if ODDS_PATH.exists() and ODDS_PATH.stat().st_size > 80:
        return "demo"
    return "empty"


def set_dataset_origin(origin: str, note: str = "") -> None:
    payload = {
        "origin": origin,
        "note": note,
        "updated_at": iso_hk(now_hk()),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    ORIGIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    ORIGIN_PATH.write_text(text, encoding="utf-8")
    DOCS_ORIGIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOCS_ORIGIN_PATH.write_text(text, encoding="utf-8")


def purge_demo_tables() -> None:
    """Drop generated sample rows so backtests only see live HKJC captures."""
    write_rows(ODDS_PATH, ODDS_FIELDS, [])
    write_rows(RESULTS_PATH, RESULTS_FIELDS, [])
    write_rows(TICK_PATH, TICK_FIELDS, [])
    rebuild_odds_board()
    log("Purged demo sample CSVs — dashboard will only show live HKJC rows")


def live_capture_ready(rows: Iterable[dict]) -> bool:
    """True when a live capture stored official 啡格 (not an empty-grid 50% guess)."""
    for row in rows:
        if stored_grid(row.get("hkjc_grid") or row.get("win_grid")) == GRID_BROWN:
            return True
        if stored_grid(row.get("place_grid")) == GRID_BROWN:
            return True
    return False


def load_inbox_odds() -> list[dict]:
    path = inbox_odds_path()
    if not path.exists():
        return []
    return read_rows(path, ODDS_FIELDS)


def load_inbox_results() -> list[dict]:
    path = inbox_results_path()
    if not path.exists():
        return []
    return read_rows(path, RESULTS_FIELDS)


def load_inbox_ticks() -> list[dict]:
    path = inbox_ticks_path()
    if not path.exists():
        return []
    return read_rows(path, TICK_FIELDS)


def load_monitor_odds() -> list[dict]:
    """Dashboard rows plus stashed live rows while demo is still showing."""
    rows = load_odds()
    if dataset_origin() == "live":
        return rows
    return rows + load_inbox_odds()


def _clear_inbox() -> None:
    if not inbox_dir().exists():
        return
    write_rows(inbox_odds_path(), ODDS_FIELDS, [])
    write_rows(inbox_results_path(), RESULTS_FIELDS, [])
    write_rows(inbox_ticks_path(), TICK_FIELDS, [])


def _promote_inbox() -> None:
    """Replace demo dashboard with stashed live rows once official 啡格 exists."""
    odds = load_inbox_odds()
    results = load_inbox_results()
    ticks = load_inbox_ticks()
    purge_demo_tables()
    if odds:
        upsert(ODDS_PATH, ODDS_FIELDS, odds, _key_odds)
    if results:
        upsert(RESULTS_PATH, RESULTS_FIELDS, results, _key_result)
    if ticks:
        upsert(TICK_PATH, TICK_FIELDS, ticks, _key_tick)
    rebuild_odds_board()
    _clear_inbox()
    set_dataset_origin(
        "live",
        "demo replaced after a live capture stored official 啡格",
    )
    log(f"Promoted live inbox over demo ({len(odds)} odds, {len(results)} results, {len(ticks)} ticks)")


def _stash_or_write(main_path: Path, inbox_path: Path, fields: list[str], incoming: list[dict], key_fn) -> int:
    """Write live rows to the dashboard once origin is live; otherwise stash until 啡格 arrives."""
    if not incoming:
        return 0
    if dataset_origin() == "live":
        return upsert(main_path, fields, incoming, key_fn)
    inbox_dir().mkdir(parents=True, exist_ok=True)
    added = upsert(inbox_path, fields, incoming, key_fn)
    if live_capture_ready(load_inbox_odds()) or live_capture_ready(load_inbox_ticks()):
        _promote_inbox()
    else:
        log("Kept demo CSVs — live capture has no official 啡格 yet; stashed in data/live_inbox")
    return added


def upsert_odds(rows: list[dict]) -> int:
    added = _stash_or_write(ODDS_PATH, inbox_odds_path(), ODDS_FIELDS, rows, _key_odds)
    if dataset_origin() == "live":
        rebuild_odds_board()
    return added


def upsert_results(rows: list[dict]) -> int:
    return _stash_or_write(RESULTS_PATH, inbox_results_path(), RESULTS_FIELDS, rows, _key_result)


def load_odds() -> list[dict]:
    return read_rows(ODDS_PATH, ODDS_FIELDS)


def load_results() -> list[dict]:
    return read_rows(RESULTS_PATH, RESULTS_FIELDS)


def upsert_ticks(rows: list[dict]) -> int:
    return _stash_or_write(TICK_PATH, inbox_ticks_path(), TICK_FIELDS, rows, _key_tick)


def load_ticks() -> list[dict]:
    return read_rows(TICK_PATH, TICK_FIELDS)


def _same_id(value, expected) -> bool:
    return str(value or "").strip() == str(expected or "").strip()


def _drop_matching(rows: list[dict], race_date: str, venue: str, race_no, horse_no=None) -> list[dict]:
    keep = []
    for row in rows:
        if not (
            _same_id(row.get("race_date"), race_date)
            and _same_id(row.get("venue"), venue)
            and _same_id(row.get("race_no"), race_no)
            and (horse_no is None or _same_id(row.get("horse_no"), horse_no))
        ):
            keep.append(row)
    return keep


def drop_odds_for_race(race_date: str, venue: str, race_no) -> int:
    """Remove snapshots for one race so a delayed postTime can be recaptured cleanly."""
    removed = 0
    for path, loader, fields, is_ticks in (
        (ODDS_PATH, load_odds, ODDS_FIELDS, False),
        (TICK_PATH, load_ticks, TICK_FIELDS, True),
        (inbox_odds_path(), load_inbox_odds, ODDS_FIELDS, False),
        (inbox_ticks_path(), load_inbox_ticks, TICK_FIELDS, True),
    ):
        if not path.exists() and path in {inbox_odds_path(), inbox_ticks_path()}:
            continue
        rows = loader()
        keep = _drop_matching(rows, race_date, venue, race_no)
        n = len(rows) - len(keep)
        if not n:
            continue
        write_rows(path, fields, keep)
        removed += n if not is_ticks else 0
        if path == ODDS_PATH:
            rebuild_odds_board()
    if removed:
        log(f"Dropped {removed} odds rows for {race_date} {venue} R{race_no} after schedule change")
    return removed


def drop_horse_odds(race_date: str, venue: str, race_no, horse_no) -> int:
    """Remove a scratched/withdrawn horse so strategy cannot pick a non-runner."""
    removed = 0
    for path, loader, fields in (
        (ODDS_PATH, load_odds, ODDS_FIELDS),
        (inbox_odds_path(), load_inbox_odds, ODDS_FIELDS),
    ):
        if not path.exists() and path == inbox_odds_path():
            continue
        rows = loader()
        keep = _drop_matching(rows, race_date, venue, race_no, horse_no)
        n = len(rows) - len(keep)
        if not n:
            continue
        write_rows(path, fields, keep)
        removed += n
        if path == ODDS_PATH:
            rebuild_odds_board()
    if removed:
        log(f"Dropped {removed} odds rows for scratched {race_date} {venue} R{race_no} #{horse_no}")
    return removed


def apply_official_sp(results: list[dict], threshold: float = 50.0) -> int:
    """Replace T-0 win odds with official 獨贏賠率 (SP) and recompute 啡格 vs T-1."""
    if not results:
        return 0
    sp_map: dict[tuple, float] = {}
    for row in results:
        sp = parse_odds(row.get("final_sp"))
        if sp is None:
            continue
        sp_map[_key_result(row)] = sp
    if not sp_map:
        return 0
    odds_path = ODDS_PATH if dataset_origin() == "live" else inbox_odds_path()
    if dataset_origin() != "live" and not odds_path.exists():
        return 0
    odds = read_rows(odds_path, ODDS_FIELDS) if odds_path.exists() else load_odds()
    t1: dict[tuple, float] = {}
    for row in odds:
        if str(row.get("checkpoint") or "").upper() != "T-1":
            continue
        win = parse_odds(row.get("win_odds"))
        if win is not None:
            t1[_key_result(row)] = win
    changed = 0
    updated: list[dict] = []
    for row in odds:
        key = _key_result(row)
        if str(row.get("checkpoint") or "").upper() != "T-0" or key not in sp_map:
            updated.append(row)
            continue
        sp = sp_map[key]
        prev = t1.get(key)
        drop = win_drop_pct(prev, sp) if prev is not None else 0.0
        new = dict(row)
        new["win_odds"] = sp
        new["prev_win_odds"] = "" if prev is None else prev
        new["win_drop_pct"] = drop
        new["is_brown_grid"] = "true" if official_brown(new.get("hkjc_grid"), drop, threshold) else "false"
        if parse_odds(row.get("win_odds")) != sp:
            changed += 1
        updated.append(new)
    if changed:
        write_rows(odds_path, ODDS_FIELDS, updated)
        if dataset_origin() == "live":
            rebuild_odds_board(threshold)
        log(f"Backfilled {changed} T-0 rows from official SP")
    return changed


def drop_date(race_date: str) -> tuple[int, int]:
    """Delete every odds and result row for one calendar date (manual repair)."""
    odds = load_odds()
    results = load_results()
    keep_odds = [row for row in odds if not _same_id(row.get("race_date"), race_date)]
    keep_results = [row for row in results if not _same_id(row.get("race_date"), race_date)]
    ticks = load_ticks()
    keep_ticks = [row for row in ticks if not _same_id(row.get("race_date"), race_date)]
    inbox_odds = load_inbox_odds()
    inbox_results = load_inbox_results()
    inbox_ticks = load_inbox_ticks()
    keep_inbox_odds = [row for row in inbox_odds if not _same_id(row.get("race_date"), race_date)]
    keep_inbox_results = [row for row in inbox_results if not _same_id(row.get("race_date"), race_date)]
    keep_inbox_ticks = [row for row in inbox_ticks if not _same_id(row.get("race_date"), race_date)]
    n_odds = len(odds) - len(keep_odds)
    n_results = len(results) - len(keep_results)
    n_ticks = len(ticks) - len(keep_ticks)
    if n_odds:
        write_rows(ODDS_PATH, ODDS_FIELDS, keep_odds)
        rebuild_odds_board()
    if n_results:
        write_rows(RESULTS_PATH, RESULTS_FIELDS, keep_results)
    if n_ticks:
        write_rows(TICK_PATH, TICK_FIELDS, keep_ticks)
    if len(inbox_odds) != len(keep_inbox_odds):
        write_rows(inbox_odds_path(), ODDS_FIELDS, keep_inbox_odds)
    if len(inbox_results) != len(keep_inbox_results):
        write_rows(inbox_results_path(), RESULTS_FIELDS, keep_inbox_results)
    if len(inbox_ticks) != len(keep_inbox_ticks):
        write_rows(inbox_ticks_path(), TICK_FIELDS, keep_inbox_ticks)
    if n_odds or n_results or n_ticks:
        log(f"Dropped {n_odds} odds + {n_results} result + {n_ticks} tick rows for {race_date}")
    return n_odds, n_results


def copy_to_docs() -> None:
    """Mirror canonical CSVs into docs/ so GitHub Pages can read them."""
    mapping = [
        (ODDS_PATH, DOCS_DATA / "odds_snapshots.csv"),
        (BOARD_PATH, DOCS_DATA / "odds_board.csv"),
        (WIN_BOARD_PATH, DOCS_DATA / "win_board.csv"),
        (PLACE_BOARD_PATH, DOCS_DATA / "place_board.csv"),
        (RESULTS_PATH, DOCS_DATA / "race_results.csv"),
        (TICK_PATH, DOCS_DATA / "odds_ticks.csv"),
        (ORIGIN_PATH, DOCS_ORIGIN_PATH),
        (ROOT / "config.json", ROOT / "docs" / "config.json"),
        (ROOT / "status.json", ROOT / "docs" / "status.json"),
        (ROOT / "logs" / "latest.log", ROOT / "docs" / "logs" / "latest.log"),
    ]
    for src, dest in mapping:
        if not src.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
