"""Edit the watchlist from the command line instead of by hand (#19).

    python manage_watchlist.py rollover amd-cpu --new zen6 --label "Ryzen 10000 (Zen 6)" --chips ryzen:10 --dry-run
    python manage_watchlist.py retire "Ryzen 7 5800X3D"
    python manage_watchlist.py retire --series zen3
    python manage_watchlist.py retire --stale
    python manage_watchlist.py check

rollover edits db/generations.toml only; the CSV is untouched and seed.py
applies the tier changes. retire edits db/watchlist.csv (status retired).
Every writing command takes --dry-run, which prints the diff and writes nothing.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from typing import Dict, List

import config
from config import GENERATIONS_PATH, WATCHLIST_PATH
from db.generations import GenerationsError, parse_generations
from db.watchlist import WatchlistRowError, read_watchlist_rows, validate_row
from scraper.chip_key import chip_key
from watchlist_edit import insert_series, set_status, unified

CSV_PATH = str(WATCHLIST_PATH)
TOML_PATH = str(GENERATIONS_PATH)

SEED_HINT = "Next: python seed.py --dry-run, then python seed.py --allow-bulk (on the host after deploy)."


def _read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def cmd_rollover(args) -> int:
    old_toml = _read(TOML_PATH)
    try:
        old_gens = parse_generations(old_toml, TOML_PATH)
        new_toml = insert_series(old_toml, args.line, args.new, args.label, args.chips)
        new_gens = parse_generations(new_toml, TOML_PATH)
    except (ValueError, GenerationsError) as e:
        print(f"ERROR: {e}")
        return 1
    for row in read_watchlist_rows(CSV_PATH):
        line_no = row.pop("_line_no", None)
        try:
            before = validate_row(dict(row), line_no, old_gens)
            after = validate_row(dict(row), line_no, new_gens)
        except WatchlistRowError as e:
            print(f"ERROR: {e}")
            return 1
        if before["gen_tier"] != after["gen_tier"]:
            print(f"{before['model']}: {before['gen_tier'] or 'out of scope'} -> {after['gen_tier'] or 'out of scope'}")
        if before["tracked"] and not after["tracked"]:
            print(f"RETIRE {before['model']}")
    print(unified(old_toml, new_toml, "generations.toml"), end="")
    if args.dry_run:
        print("Dry run: nothing written.")
    else:
        _write(TOML_PATH, new_toml)
        print(f"Wrote {TOML_PATH}. Now add the new series' SKU rows to the CSV.")
    print(SEED_HINT)
    return 0


def _stale_models() -> List[str]:
    """Models with a pending or requested retire suggestion. Read-only on config.DB_PATH."""
    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT p.model FROM retire_suggestions r JOIN products p ON p.id = r.product_id "
            "WHERE r.decision IN ('pending','requested')"
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def cmd_retire(args) -> int:
    old_csv = _read(CSV_PATH)
    rows = read_watchlist_rows(CSV_PATH)
    if args.series:
        models = {r["model"] for r in rows if (r.get("series") or "").strip() == args.series}
        if not models:
            print(f"ERROR: no rows with series {args.series!r}")
            return 1
    elif args.stale:
        models = set(_stale_models())
        if not models:
            print("No stale suggestions to retire.")
            return 0
    elif args.model:
        models = {args.model}
    else:
        print("ERROR: give a model, --series KEY or --stale")
        return 1
    known = {(r.get("model") or "").strip().lower() for r in rows}
    missing = sorted(m for m in models if m.strip().lower() not in known)
    for m in missing:
        print(f"ERROR: model not found in watchlist: {m}")
    new_csv, changed = set_status(old_csv, models, "retired")
    for m in changed:
        print(f"RETIRE {m}")
    print(unified(old_csv, new_csv, "watchlist.csv"), end="")
    if missing:
        print("Nothing written (fix the names above).")
        return 1
    if args.dry_run:
        print("Dry run: nothing written.")
    elif changed:
        _write(CSV_PATH, new_csv)
        print(f"Wrote {CSV_PATH}.")
    else:
        print("Already retired: nothing to change.")
    if changed:
        print(SEED_HINT)
    return 0


def cmd_check(args) -> int:
    from sync_specs import SPECS_UNAVAILABLE_UPSTREAM

    problems: List[str] = []
    try:
        gens = parse_generations(_read(TOML_PATH), TOML_PATH)
    except (GenerationsError, OSError) as e:
        print(f"PROBLEM: {e}")
        return 1
    # Collisions span ALL rows, retired included: two rows with one
    # (category, chip key, spec) make the Matcher drop the listing silently.
    groups: Dict[tuple, List[str]] = {}
    models = set()
    n = 0
    for row in read_watchlist_rows(CSV_PATH):
        line_no = row.pop("_line_no", None)
        n += 1
        try:
            v = validate_row(row, line_no, gens)
        except WatchlistRowError as e:
            problems.append(str(e))
            continue
        models.add(v["model"])
        key = chip_key(v["model"], v["category"])
        if key is None:
            problems.append(f"watchlist row {line_no} [model]: no chip key for {v['model']!r}")
            continue
        groups.setdefault((v["category"], key, v["spec"].strip().lower()), []).append(v["model"])
    for (cat, key, spec), names in groups.items():
        if len(names) > 1:
            problems.append(
                f"collision: {' and '.join(names)} share {cat} chip key {key!r} with spec {spec!r}; "
                "the matcher would drop their listings"
            )
    for name in SPECS_UNAVAILABLE_UPSTREAM:
        if name not in models:
            problems.append(f"SPECS_UNAVAILABLE_UPSTREAM names {name!r}, which is not in the watchlist")
    if problems:
        for p in problems:
            print(f"PROBLEM: {p}")
        print(f"{len(problems)} problem(s).")
        return 1
    print(f"OK: {n} rows, {len(gens.series)} series")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("rollover", help="add a new newest series to a line (edits generations.toml)")
    r.add_argument("line", help="line id, e.g. amd-cpu")
    r.add_argument("--new", required=True, help="new series key, e.g. zen6")
    r.add_argument("--label", required=True)
    r.add_argument("--chips", required=True, type=lambda s: [c for c in s.split(",") if c],
                   help="comma-separated family:gen tokens, e.g. ryzen:10")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(func=cmd_rollover)

    t = sub.add_parser("retire", help="set rows to retired (edits watchlist.csv)")
    t.add_argument("model", nargs="?")
    t.add_argument("--series")
    t.add_argument("--stale", action="store_true", help="every pending/requested retire suggestion")
    t.add_argument("--dry-run", action="store_true")
    t.set_defaults(func=cmd_retire)

    c = sub.add_parser("check", help="validate generations.toml and watchlist.csv")
    c.set_defaults(func=cmd_check)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
