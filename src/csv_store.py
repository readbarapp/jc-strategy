"""Append / upsert CSV tables used by the Pages frontend."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .logger import log
from .odds_board import WIDE_FIELDS, pivot_odds
from .schema import ODDS_FIELDS, RESULTS_FIELDS
from .timeutil import iso_hk, now_hk

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DOCS_DATA = ROOT / "docs" / "data"
ODDS_PATH = DATA_DIR / "odds_snapshots.csv"
RESULTS_PATH = DATA_DIR / "race_results.csv"
BOARD_PATH = DATA_DIR / "odds_board.csv"
WIN_BOARD_PATH = DATA_DIR / "win_board.csv"
PLACE_BOARD_PATH = DATA_DIR / "place_board.csv"
ORIGIN_PATH = DATA_DIR / "dataset_origin.json"
DOCS_ORIGIN_PATH = DOCS_DATA / "dataset_origin.json"


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
    rebuild_odds_board()
    log("Purged demo sample CSVs — dashboard will only show live HKJC rows")


def prepare_for_live_rows(incoming: list[dict]) -> bool:
    """On the first real capture, delete every demo row. Returns True if a purge ran."""
    if not incoming:
        return False
    if dataset_origin() == "live":
        return False
    purge_demo_tables()
    set_dataset_origin(
        "live",
        "demo sample deleted after the first live HKJC capture",
    )
    return True


def upsert_odds(rows: list[dict]) -> int:
    prepare_for_live_rows(rows)
    added = upsert(ODDS_PATH, ODDS_FIELDS, rows, _key_odds)
    rebuild_odds_board()
    return added


def upsert_results(rows: list[dict]) -> int:
    prepare_for_live_rows(rows)
    return upsert(RESULTS_PATH, RESULTS_FIELDS, rows, _key_result)


def load_odds() -> list[dict]:
    return read_rows(ODDS_PATH, ODDS_FIELDS)


def load_results() -> list[dict]:
    return read_rows(RESULTS_PATH, RESULTS_FIELDS)


def _same_id(value, expected) -> bool:
    return str(value or "").strip() == str(expected or "").strip()


def drop_odds_for_race(race_date: str, venue: str, race_no) -> int:
    """Remove snapshots for one race so a delayed postTime can be recaptured cleanly."""
    rows = load_odds()
    keep = [
        row
        for row in rows
        if not (
            _same_id(row.get("race_date"), race_date)
            and _same_id(row.get("venue"), venue)
            and _same_id(row.get("race_no"), race_no)
        )
    ]
    removed = len(rows) - len(keep)
    if removed:
        write_rows(ODDS_PATH, ODDS_FIELDS, keep)
        rebuild_odds_board()
        log(f"Dropped {removed} odds rows for {race_date} {venue} R{race_no} after schedule change")
    return removed


def drop_horse_odds(race_date: str, venue: str, race_no, horse_no) -> int:
    """Remove a scratched/withdrawn horse so strategy cannot pick a non-runner."""
    rows = load_odds()
    keep = [
        row
        for row in rows
        if not (
            _same_id(row.get("race_date"), race_date)
            and _same_id(row.get("venue"), venue)
            and _same_id(row.get("race_no"), race_no)
            and _same_id(row.get("horse_no"), horse_no)
        )
    ]
    removed = len(rows) - len(keep)
    if removed:
        write_rows(ODDS_PATH, ODDS_FIELDS, keep)
        rebuild_odds_board()
        log(f"Dropped {removed} odds rows for scratched {race_date} {venue} R{race_no} #{horse_no}")
    return removed


def drop_date(race_date: str) -> tuple[int, int]:
    """Delete every odds and result row for one calendar date (manual repair)."""
    odds = load_odds()
    results = load_results()
    keep_odds = [row for row in odds if not _same_id(row.get("race_date"), race_date)]
    keep_results = [row for row in results if not _same_id(row.get("race_date"), race_date)]
    n_odds = len(odds) - len(keep_odds)
    n_results = len(results) - len(keep_results)
    if n_odds:
        write_rows(ODDS_PATH, ODDS_FIELDS, keep_odds)
        rebuild_odds_board()
    if n_results:
        write_rows(RESULTS_PATH, RESULTS_FIELDS, keep_results)
    if n_odds or n_results:
        log(f"Dropped {n_odds} odds + {n_results} result rows for {race_date}")
    return n_odds, n_results


def copy_to_docs() -> None:
    """Mirror canonical CSVs into docs/ so GitHub Pages can read them."""
    mapping = [
        (ODDS_PATH, DOCS_DATA / "odds_snapshots.csv"),
        (BOARD_PATH, DOCS_DATA / "odds_board.csv"),
        (WIN_BOARD_PATH, DOCS_DATA / "win_board.csv"),
        (PLACE_BOARD_PATH, DOCS_DATA / "place_board.csv"),
        (RESULTS_PATH, DOCS_DATA / "race_results.csv"),
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
