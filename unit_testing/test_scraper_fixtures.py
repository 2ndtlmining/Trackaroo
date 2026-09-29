"""Each scraper's parser against real, trimmed retailer markup (#14).

When a retailer changes its HTML, re-run unit_testing/fixtures/capture_fixtures.py
(owner OK -- 3 live requests) and the diff of the fixture shows what moved.
"""
import json
import unittest.mock
from pathlib import Path

from health_checks import CheckResult, check_run_report
from scraper import pccg, scorptec, umart

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STOCK = {"in_stock", "out_of_stock", "preorder", "unknown"}


def _fixture(name):
    path = FIXTURES / name
    assert path.exists(), f"{name} missing - run python unit_testing/fixtures/capture_fixtures.py"
    return path.read_text(encoding="utf-8")


class TestScorptecFixture:
    HTML = "scorptec_gpu_nvidia_page1.html"

    def test_every_card_parses(self):
        stats = {}
        products = scorptec.parse_product_grid(_fixture(self.HTML), "graphics-cards/nvidia", stats=stats)

        assert (stats["cards_seen"], stats["cards_dropped"]) == (8, 0)
        assert len(products) == 8
        for p in products:
            assert p["price_aud"] > 0
            assert p["url"].startswith("https://www.scorptec.com.au/")
            assert p["retailer_sku"]
            assert p["stock_status"] in STOCK

    def test_the_page_has_no_next_link_today(self):
        """The live capture (29-Sep-2026) of the NVIDIA GPU grid's page 1 carried
        no ``a.next[href]`` anywhere in the response -- the category currently
        fits on one page. The plan assumed a next-page link would be present;
        it wasn't, so this asserts what the fixture actually holds (a real
        "last page" case) rather than fabricating a link that was never
        captured. Re-run the capture (owner OK) if this needs re-checking."""
        assert scorptec.get_next_page_url(_fixture(self.HTML), scorptec.CATEGORY_URLS["gpu_nvidia"]) is None

    def test_a_renamed_grid_class_is_reported_as_selector_drift(self):
        html = _fixture(self.HTML).replace("product-grid", "product-tile")
        stats = {"pages_attempted": 1, "pages_fetched": 1}

        assert scorptec.parse_product_grid(html, "graphics-cards/nvidia", stats=stats) == []
        results = check_run_report({"retailer": "scorptec", "categories": {"gpu": stats}})

        assert [r.status for r in results] == [CheckResult.ERROR]
        assert "selector drift at scorptec/gpu" in results[0].message


class TestUmartFixture:
    HTML = "umart_cpu_page1.html"

    def test_every_card_parses(self):
        stats = {}
        products = umart.parse_product_grid(_fixture(self.HTML), stats=stats)

        assert (stats["cards_seen"], stats["cards_dropped"]) == (8, 0)
        for p in products:
            assert p["price_aud"] > 0
            assert p["url"].startswith("https://www.umart.com.au/")
            assert p["retailer_sku"]
            assert p["stock_status"] in STOCK

    def test_the_page_count_comes_from_the_pager(self):
        assert umart.get_max_page(_fixture(self.HTML)) >= 2

    def test_a_503_on_page_2_of_3_is_a_pagination_hole(self, monkeypatch):
        html = _fixture(self.HTML)
        pages = {"x": html, "x?page=2": None, "x?page=3": html}
        monkeypatch.setattr("scraper.umart.get_max_page", lambda h: 3)
        monkeypatch.setattr("scraper.umart.fetch_page", lambda url, retries=None: pages[url])
        monkeypatch.setattr("scraper.umart.time.sleep", lambda s: None)
        stats = {}

        umart.scrape_all_pages("x", stats=stats)
        results = check_run_report({"retailer": "umart", "categories": {"cpu": stats}})

        assert (stats["pages_attempted"], stats["pages_fetched"]) == (3, 2)
        assert [(r.status, r.check_name) for r in results] == [(CheckResult.WARNING, "pagination_hole_umart_cpu")]


class TestPccgFixture:
    JSON = "pccg_cpus_catalogue.json"

    def test_every_hit_extracts(self):
        hits = json.loads(_fixture(self.JSON))["results"][0]["hits"]
        products = pccg._extract_products(hits)

        assert len(hits) == 20 and len(products) == 20
        for p in products:
            assert p["url"].startswith("https://www.pccasegear.com")
            assert pccg._parse_price(p["price"]) > 0
            assert p["stock_status"] in STOCK

    def test_the_catalogue_fetch_counts_its_page_and_cards(self, monkeypatch):
        payload = json.loads(_fixture(self.JSON))

        def post(*a, **k):
            resp = unittest.mock.Mock()
            resp.status_code = 200
            resp.headers = {}
            resp.json.return_value = payload
            return resp

        monkeypatch.setattr("scraper.pccg.requests.post", post)
        stats = {}

        assert len(pccg.algolia_fetch_catalogue("CPUs", stats=stats)) == 20
        assert stats == {"pages_attempted": 1, "pages_fetched": 1, "cards_seen": 20, "cards_dropped": 0}
