"""One-off capture of real retailer pages for the scraper fixture tests (#14).

Run by hand, with the owner's OK, never from a test or CI. It makes three live
requests: one Scorptec NVIDIA grid page, Umart's CPU category page 1, and one
Algolia query for PCC's CPUs (hitsPerPage=20, which is 1 of the key's 100
queries/hour). Each page is cut to its first 8 product cards plus the
pagination links, with scripts and styles removed, so the fixtures stay small
and a retailer's markup change shows up as a readable diff.

    python unit_testing/fixtures/capture_fixtures.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scraper import pccg, scorptec, umart  # noqa: E402

HERE = Path(__file__).resolve().parent
KEEP_CARDS = 8


def _trim(html: str, card_selector: str, pager_selector: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    kept = soup.select(card_selector)[:KEEP_CARDS] + soup.select(pager_selector)
    for tag in kept:
        for junk in tag.find_all(["script", "style"]):
            junk.decompose()
    body = "\n".join(str(t) for t in kept)
    return f"<html><body>\n{body}\n</body></html>\n"


def main() -> None:
    s_html = scorptec.fetch_page(scorptec.CATEGORY_URLS["gpu_nvidia"])
    u_html = umart.fetch_page(umart.CATEGORY_URLS["cpu"])
    if not s_html or not u_html:
        raise SystemExit("A fetch failed - nothing written.")
    (HERE / "scorptec_gpu_nvidia_page1.html").write_text(
        _trim(s_html, ".product-grid", "a.next[href]"), encoding="utf-8")
    (HERE / "umart_cpu_page1.html").write_text(
        _trim(u_html, ".goods-item", "a[href*='page=']"), encoding="utf-8")

    params = urlencode({
        "query": "", "hitsPerPage": 20, "page": 0,
        "attributesToRetrieve": pccg.STOCK_ATTRS,
        "filters": 'categories.lvl0:"CPUs"',
    })
    r = requests.post(pccg.ALGOLIA_URL, headers=pccg.HEADERS, timeout=15,
                      json={"requests": [{"indexName": pccg.ALGOLIA_INDEX, "params": params}]})
    r.raise_for_status()
    payload = r.json()
    # One page is the fixture: stop algolia_fetch_catalogue paginating over it.
    payload["results"][0]["nbPages"] = 1
    (HERE / "pccg_cpus_catalogue.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote 3 fixtures to {HERE}")


if __name__ == "__main__":
    main()
