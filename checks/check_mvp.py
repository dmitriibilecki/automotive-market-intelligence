import csv
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from bs4 import BeautifulSoup

from car_bot import config
from car_bot.analysis.market import analyze_market
from car_bot.parsers.olx_parser import extract_search_json_ld_urls, parse_listing_html
from car_bot.storage.db import export_csv, init_db, insert_listing, listing_exists


class MvpParserChecks(unittest.TestCase):
    def test_parse_listing_html_returns_only_allowed_fields(self):
        html = """
        <html>
          <head>
            <script type="application/ld+json">
            {
              "@context": "https://schema.org",
              "@type": "Vehicle",
              "name": "BMW 320d",
              "url": "https://www.olx.pl/d/oferta/bmw-320d-CID5-IDabc123.html?search=1",
              "sku": "107",
              "brand": "BMW",
              "model": "Seria 3",
              "productionDate": "2018",
              "description": "Do not store listing description",
              "seller": {"name": "Seller Name", "email": "seller@example.com"},
              "offers": {
                "@type": "Offer",
                "price": 42000,
                "areaServed": {"@type": "City", "name": "Warszawa"}
              }
            }
            </script>
          </head>
          <body>
            <h1>BMW 320d</h1>
            <p>Przebieg: 120 000 km</p>
            <p>Rodzaj paliwa: Diesel</p>
            <p>Skrzynia bieg\u00f3w: Automatyczna</p>
            <p>Typ nadwozia: Sedan</p>
            <p>Pojemno\u015b\u0107 silnika: 1995 cm3</p>
            <p>Moc: 190 KM</p>
          </body>
        </html>
        """

        listing = parse_listing_html(html, "https://www.olx.pl/d/oferta/fallback-CID5-IDx.html")

        self.assertEqual(set(listing), set(config.FIELDS))
        self.assertEqual(listing["external_id"], "107")
        self.assertEqual(listing["url"], "https://www.olx.pl/d/oferta/bmw-320d-CID5-IDabc123.html")
        self.assertEqual(listing["price"], 42000)
        self.assertEqual(listing["mileage"], 120000)
        self.assertNotIn("seller", listing)
        self.assertNotIn("description", listing)

    def test_extract_search_json_ld_urls_reads_nested_offers(self):
        html = """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "offers": {
            "@type": "AggregateOffer",
            "offers": [
              {"@type": "Offer", "url": "https://www.olx.pl/d/oferta/car-one-CID5-IDone.html?x=1"},
              {"@type": "Offer", "url": "/d/oferta/car-two-CID5-IDtwo.html"},
              {"@type": "Offer", "url": "https://www.otomoto.pl/osobowe/oferta/test"}
            ]
          }
        }
        </script>
        """

        urls = extract_search_json_ld_urls(BeautifulSoup(html, "html.parser"))

        self.assertEqual(
            urls,
            [
                "https://www.olx.pl/d/oferta/car-one-CID5-IDone.html",
                "https://www.olx.pl/d/oferta/car-two-CID5-IDtwo.html",
            ],
        )

    def test_storage_deduplicates_by_url_and_exports_csv(self):
        listing = {field: None for field in config.FIELDS}
        listing.update(
            {
                "source": "olx",
                "external_id": "IDone",
                "url": "https://www.olx.pl/d/oferta/car-one-CID5-IDone.html",
                "title": "BMW",
                "price": 10000,
                "scraped_at": "2026-05-28T00:00:00+00:00",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with closing(sqlite3.connect(Path(tmpdir) / "baza_ogloszen.sqlite")) as conn:
                conn.row_factory = sqlite3.Row
                init_db(conn)

                self.assertTrue(insert_listing(conn, listing))
                self.assertFalse(insert_listing(conn, listing))
                self.assertTrue(listing_exists(conn, listing["url"]))

                csv_path = Path(tmpdir) / "eksport_ogloszen.csv"
                export_csv(conn, csv_path)
                with csv_path.open(encoding="utf-8-sig", newline="") as file:
                    rows = list(csv.DictReader(file))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], listing["url"])

    def test_market_report_thresholds(self):
        report = analyze_market(
            [
                {"price": 10000, "url": "one"},
                {"price": 20000, "url": "two"},
                {"price": 30000, "url": "three"},
                {"price": 40000, "url": "four"},
            ]
        )

        self.assertEqual(report["count"], 4)
        self.assertEqual(report["min_price"], 10000)
        self.assertEqual(report["median_price"], 25000.0)
        self.assertEqual(report["p25"], 17500.0)
        self.assertEqual(report["p10"], 13000.0)
        self.assertEqual([item["url"] for item in report["cheap"]], ["one"])
        self.assertEqual([item["url"] for item in report["very_cheap"]], ["one"])


if __name__ == "__main__":
    unittest.main()
