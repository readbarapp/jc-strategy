"""Append / upsert CSV tables used by the Pages frontend."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .odds_board import WIDE_FIELDS, pivot_odds
from .schema import ODDS_FIELDS, RESULTS_FIELDS

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DOCS_DATA = ROOT / "docs" / "data"
ODDS_PATH = DATA_DIR / "odds_snapshots.csv"
RESULTS_PATH = DATA_DIR / "race_results.csv"
BOARD_PATH = DATA_DIR / "odds_board.csv"
WIN_BOARD_PATH = DATA_DIR / "win_board.csv"
PLACE_BOARD_PATH = DATA_DIR / "place_board.csv"


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


def upsert_odds(rows: list[dict]) -> int:
    added = upsert(ODDS_PATH, ODDS_FIELDS, rows, _key_odds)
    rebuild_odds_board()
    return added


def upsert_results(rows: list[dict]) -> int:
    return upsert(RESULTS_PATH, RESULTS_FIELDS, rows, _key_result)


def load_odds() -> list[dict]:
    return read_rows(ODDS_PATH, ODDS_FIELDS)


def load_results() -> list[dict]:
    return read_rows(RESULTS_PATH, RESULTS_FIELDS)


def copy_to_docs() -> None:
    """Mirror canonical CSVs into docs/ so GitHub Pages can read them."""
    mapping = [
        (ODDS_PATH, DOCS_DATA / "odds_snapshots.csv"),
        (BOARD_PATH, DOCS_DATA / "odds_board.csv"),
        (WIN_BOARD_PATH, DOCS_DATA / "win_board.csv"),
        (PLACE_BOARD_PATH, DOCS_DATA / "place_board.csv"),
        (RESULTS_PATH, DOCS_DATA / "race_results.csv"),
        (ROOT / "config.json", ROOT / "docs" / "config.json"),
        (ROOT / "status.json", ROOT / "docs" / "status.json"),
        (ROOT / "logs" / "latest.log", ROOT / "docs" / "logs" / "latest.log"),
    ]
    for src, dest in mapping:
        if not src.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
