# discover.py
"""Discovery report (#16): parts retailers sell that the watchlist does not track.

Runs from run_daily.py after ingest, through best_effort() -- it can never
break a run. Reads today's data/catalogue/ files (scraper/catalogue_io.py),
classifies every item (discover_rules.py), keeps one discovered_parts row per
untracked part, records listings filed under the wrong product as
discovery_conflicts, and posts parts seen for the first time to Discord once.
A run never overwrites a decision (status/notified_at/decided_at); the only
automatic status change is untracked|requested -> tracked when the watchlist
now resolves the part (here from today's catalogues, and from seed.py via
flip_resolved() at every boot/redeploy). See README "Discovering and adding new parts".
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import discover_rules as rules
from config import ACTIVE_RETAILERS, DATA_DIR, DB_PATH, FILE_DATE_FORMAT
from db.watchlist import load_retired, load_watchlist
from migrate import migrate_add_discovery_tables
from scraper.catalogue_io import load_catalogues, prune_catalogues
from scraper.chip_key import Matcher, chip_key, parse_vram

LOGGER = logging.getLogger(__name__)

CATALOGUE_KEEP_DAYS = 30
RUNS_KEEP = 30
SAMPLE_TITLES = 5
UNRECOGNISED_SAMPLES = 20
HOLDING_BRAND = "Unmatched"  # repair_listings.HOLDING_BRAND


_TABLES = ("discovered_parts", "discovery_conflicts", "discovery_runs")


def _missing_tables(conn: sqlite3.Connection) -> bool:
    # migrate_add_discovery_tables logs a [SKIP] line per existing table; only call it when needed.
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return not set(_TABLES) <= have


def _group_key(category: str, title: str) -> Optional[Tuple[str, Optional[int]]]:
    key = chip_key(title, category)
    if key is None:
        return None
    vram = parse_vram(title) if category == "gpu" else None
    return key, vram


def _classify(envelopes, matcher, watchlist=()) -> Tuple[Dict[Tuple[str, str], Dict[str, Any]], Set[Tuple[str, str]], List[str]]:
    """(untracked groups by (category, part_key), part keys now tracked, unrecognised titles)."""
    # Retired rows are known chips (not new parts), but they are not 'tracked': a
    # retired part must not flip its discovered_parts row to status 'tracked'.
    known_chips = {(wp["category"], chip_key(wp["model"], wp["category"])) for wp in watchlist}
    tracked_chips = _tracked_chips(watchlist)
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    tracked: Set[Tuple[str, str]] = set()
    unrecognised: List[str] = []
    for env in envelopes:
        category, retailer = env.get("category"), env.get("retailer")
        if category not in ("cpu", "gpu"):
            continue
        for item in env["items"]:
            title = (item.get("title") or "").strip()
            if not title or rules.is_excluded_title(title):
                continue
            url = (item.get("url") or "").lower()
            if "-bdl-" in url or "/bundle/" in url:
                continue  # retailer bundle page, skipped by the scrapers too
            kv = _group_key(category, title)
            if kv is None:
                unrecognised.append(title)
                continue
            key, vram = kv
            if rules.series_tier(category, key) is None:
                continue
            pkey = rules.part_key(category, key, vram)
            idx = matcher.resolve(title, category)
            if idx is not None or (vram is None and (category, key) in known_chips):
                # Known: a watchlist row, or a known chip whose title just omits the VRAM.
                if _tracked_by(matcher, idx, category, key, vram, tracked_chips):
                    tracked.add((category, pkey))
                continue
            g = groups.setdefault((category, pkey), {
                "key": key, "vram": vram, "titles": [], "retailers": set(), "count": 0,
                "min_price": None, "min_url": None,
            })
            g["count"] += 1
            g["retailers"].add(retailer)
            if len(g["titles"]) < SAMPLE_TITLES and title not in g["titles"]:
                g["titles"].append(title)
            price = item.get("price_aud")
            if price and (g["min_price"] is None or price < g["min_price"]):
                g["min_price"], g["min_url"] = price, item.get("url")
    return groups, tracked, unrecognised


def _placeholder_first_seen(conn: sqlite3.Connection) -> Dict[Tuple[str, str], str]:
    """Earliest snapshot date of each part already parked under 'Unmatched'."""
    rows = conn.execute(
        """SELECT p.category, l.variant_name, MIN(s.snapshot_date)
           FROM retailer_listings l
           JOIN products p ON p.id = l.product_id
           JOIN price_snapshots s ON s.retailer_listing_id = l.id
           WHERE p.brand = ?
           GROUP BY l.id""",
        (HOLDING_BRAND,),
    ).fetchall()
    out: Dict[Tuple[str, str], str] = {}
    for category, title, first in rows:
        kv = _group_key(category, title or "")
        if kv is None or first is None:
            continue
        pk = (category, rules.part_key(category, *kv))
        out[pk] = min(out.get(pk, first), first)
    return out


def _upsert(conn, groups, watchlist, today_iso: str) -> None:
    # listing_count/retailers/min_price reflect today's catalogues only.
    keys_with_vram_rows = {
        chip_key(wp["model"], wp["category"]) for wp in watchlist if wp["category"] == "gpu" and wp.get("vram_gb")
    }
    existing = {
        (r[0], r[1]) for r in conn.execute("SELECT category, part_key FROM discovered_parts")
    }
    first_seen = _placeholder_first_seen(conn) if any(k not in existing for k in groups) else {}
    for (category, pkey), g in groups.items():
        titles, key, vram = g["titles"], g["key"], g["vram"]
        fields = {
            "display_name": rules.display_name(category, key, vram, titles),
            "last_seen": today_iso,
            "listing_count": g["count"],
            "retailers": ",".join(sorted(g["retailers"])),
            "min_price": g["min_price"],
            "min_price_url": g["min_url"],
            "sample_titles": json.dumps(titles),
            "suggested_row": rules.suggested_row(category, key, vram, titles,
                                                 vram_in_model=key in keys_with_vram_rows),
        }
        if (category, pkey) in existing:
            sets = ", ".join(f"{k} = :{k}" for k in fields)
            conn.execute(f"UPDATE discovered_parts SET {sets} WHERE category = :c AND part_key = :p",
                         {**fields, "c": category, "p": pkey})
        else:
            conn.execute(
                """INSERT INTO discovered_parts (category, part_key, display_name, status, first_seen, last_seen,
                       listing_count, retailers, min_price, min_price_url, sample_titles, suggested_row)
                   VALUES (:c, :p, :display_name, 'untracked', :first, :last_seen, :listing_count, :retailers,
                       :min_price, :min_price_url, :sample_titles, :suggested_row)""",
                {**fields, "c": category, "p": pkey, "first": first_seen.get((category, pkey), today_iso)},
            )


def _tracked_chips(watchlist) -> Set[Tuple[str, str]]:
    return {(wp["category"], chip_key(wp["model"], wp["category"])) for wp in watchlist if wp.get("tracked", True)}


def _tracked_by(matcher, idx, category, key, vram, tracked_chips) -> bool:
    """Whether a recognised title belongs to a tracked watchlist row (idx = matcher.resolve)."""
    if idx is not None:
        return bool(matcher.watchlist[idx].get("tracked", True))
    # A bare-key part created before the VRAM rows existed.
    return vram is None and (category, key) in tracked_chips


def flip_resolved(conn: sqlite3.Connection, watchlist=None) -> List[str]:
    """Flip untracked/requested parts the watchlist now tracks, from their stored sample titles.

    The daily run does the same from today's catalogues; seed.py calls this so a
    part added in a PR leaves Requested at deploy, not at the next 04:00 run (#90).
    Returns the display names flipped. The caller commits.
    """
    if _missing_tables(conn):
        return []
    wl = watchlist if watchlist is not None else load_watchlist() + load_retired()
    matcher, tracked_chips = Matcher(wl), _tracked_chips(wl)
    rows = conn.execute(
        "SELECT category, part_key, display_name, sample_titles FROM discovered_parts"
        " WHERE status IN ('untracked', 'requested')"
    ).fetchall()
    flipped = []
    for category, pkey, name, samples in rows:
        for title in json.loads(samples or "[]"):
            kv = _group_key(category, title)
            if kv is None:
                continue
            key, vram = kv
            if _tracked_by(matcher, matcher.resolve(title, category), category, key, vram, tracked_chips):
                _flip_tracked(conn, {(category, pkey)})
                flipped.append(name)
                break
    return flipped


def _flip_tracked(conn, tracked: Set[Tuple[str, str]]) -> None:
    for category, pkey in tracked:
        conn.execute(
            "UPDATE discovered_parts SET status = 'tracked' WHERE category = ? AND part_key = ?"
            " AND status IN ('untracked', 'requested')",
            (category, pkey),
        )


def find_conflicts(conn: sqlite3.Connection, today_iso: str) -> List[Tuple]:
    rows = conn.execute(
        """SELECT l.id, l.retailer, l.variant_name, p.id, p.category, p.model, p.vram_gb
           FROM retailer_listings l JOIN products p ON p.id = l.product_id
           WHERE l.status = 'active' AND p.tracked = 1 AND p.brand != ?""",
        (HOLDING_BRAND,),
    ).fetchall()
    out = []
    for lid, retailer, title, pid, category, model, vram_gb in rows:
        title = (title or "").strip()
        if not title:
            continue
        product_key = chip_key(model, category)
        title_key = chip_key(title, category)
        reason = None
        if rules.is_excluded_title(title):
            reason = "excluded item (bundle, laptop, workstation...) filed under a product"
        elif title_key is None:
            reason = "title names no recognisable chip"
        elif title_key != product_key:
            reason = f"title names {title_key}, product is {product_key}"
        elif category == "gpu" and vram_gb:
            v = parse_vram(title)
            if v and v != vram_gb:
                reason = f"title says {v}GB, product is {vram_gb}GB"
        if reason:
            out.append((lid, retailer, pid, title_key, reason, title, today_iso))
    return out


EMBED_MAX_LINES = 25


def build_embed(rows, base_url: str) -> dict:
    lines = []
    for r in rows[:EMBED_MAX_LINES]:
        retailers = ", ".join(r["retailers"].split(",")) if r["retailers"] else "?"
        price = f"${r['min_price']:,.0f}" if r["min_price"] else "price unknown"
        plural = "listing" if r["listing_count"] == 1 else "listings"
        lines.append(f"**{r['display_name']}**: {r['listing_count']} {plural} at {retailers}, from {price}")
    if len(rows) > EMBED_MAX_LINES:
        lines.append(f"...and {len(rows) - EMBED_MAX_LINES} more on the Discover page")
    embed = {
        "title": "New parts at retailers",
        "description": "\n".join(lines) + "\n\nTrack or Ignore each one on the Discover page.",
        "color": 0x3B82F6,
    }
    if base_url:
        embed["url"] = f"{base_url.rstrip('/')}/discover"
    return embed


def notify_new(conn: sqlite3.Connection, today_iso: str) -> int:
    """Send untracked parts never notified before; stamp them only on success."""
    import os
    import notify_discord

    notify_discord.load_dotenv()
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        return 0
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, display_name, listing_count, retailers, min_price FROM discovered_parts"
        " WHERE status = 'untracked' AND notified_at IS NULL ORDER BY first_seen DESC, display_name"
    ).fetchall()
    conn.row_factory = None
    if not rows:
        return 0
    base_url = os.environ.get("TRACKAROO_PUBLIC_BASE_URL", "")
    if not notify_discord.send_embed(webhook, build_embed(rows, base_url)):
        LOGGER.warning("Discovery notice not delivered; it will be retried on the next run")
        return 0
    stamp = datetime.now().isoformat(timespec="seconds")
    conn.executemany("UPDATE discovered_parts SET notified_at = ? WHERE id = ?", [(stamp, r["id"]) for r in rows])
    conn.commit()
    return len(rows)


def run(
    db_path: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    today: Optional[date] = None,
    notify: bool = False,
    watchlist: Optional[list] = None,
) -> Dict[str, Any]:
    # Resolved at call time so a test can redirect the module globals.
    db_path = Path(db_path) if db_path is not None else DB_PATH
    data_dir = Path(data_dir) if data_dir is not None else DATA_DIR
    today = today or date.today()
    today_iso = today.isoformat()
    file_date = today.strftime(FILE_DATE_FORMAT)
    prune_catalogues(Path(data_dir), CATALOGUE_KEEP_DAYS, today)
    envelopes, bad = load_catalogues(Path(data_dir), file_date)
    present = {f"{e.get('retailer')}/{e.get('category')}" for e in envelopes}
    missing = [f"{r}/{c}" for r in ACTIVE_RETAILERS for c in ("cpu", "gpu") if f"{r}/{c}" not in present]
    missing += [f"unreadable: {name}" for name in bad]

    conn = sqlite3.connect(str(db_path))
    try:
        if _missing_tables(conn):
            migrate_add_discovery_tables(conn)
        unrecognised: List[str] = []
        if envelopes:
            wl = watchlist if watchlist is not None else load_watchlist() + load_retired()
            groups, tracked, unrecognised = _classify(envelopes, Matcher(wl), wl)
            _upsert(conn, groups, wl, today_iso)
            _flip_tracked(conn, tracked)
        conflicts = find_conflicts(conn, today_iso)
        conn.execute("DELETE FROM discovery_conflicts")
        conn.executemany("INSERT INTO discovery_conflicts VALUES (?, ?, ?, ?, ?, ?, ?)", conflicts)
        conn.execute(
            """INSERT INTO discovery_runs (run_date, finished_at, catalogue_files, missing,
                   unrecognised_count, unrecognised_samples) VALUES (?, ?, ?, ?, ?, ?)""",
            (today_iso, datetime.now().isoformat(timespec="seconds"), len(envelopes), json.dumps(missing),
             len(unrecognised), json.dumps(unrecognised[:UNRECOGNISED_SAMPLES])),
        )
        conn.execute(
            "DELETE FROM discovery_runs WHERE id NOT IN (SELECT id FROM discovery_runs ORDER BY id DESC LIMIT ?)",
            (RUNS_KEEP,),
        )
        conn.commit()
        untracked = conn.execute("SELECT COUNT(*) FROM discovered_parts WHERE status = 'untracked'").fetchone()[0]
        new_today = conn.execute(
            "SELECT COUNT(*) FROM discovered_parts WHERE status = 'untracked' AND first_seen = ?", (today_iso,)
        ).fetchone()[0]
        notified = notify_new(conn, today_iso) if notify else 0
    finally:
        conn.close()
    summary = {"catalogue_files": len(envelopes), "untracked": untracked, "new_today": new_today,
               "conflicts": len(conflicts), "missing": missing, "notified": notified}
    LOGGER.info("Discovery: %s", summary)
    return summary


if __name__ == "__main__":
    from config import setup_logging
    setup_logging()
    print(json.dumps(run(), indent=2))
