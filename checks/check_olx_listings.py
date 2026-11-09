import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from openpyxl import load_workbook

from car_bot.olx_listings import parse_olx_listing_html, safe_external_id
from car_bot.storage.market_db import (
    connect,
    fetch_daily_brand_counts,
    fetch_listings,
    init_market_db,
    mark_missing_inactive,
    refresh_daily_brand_counts,
    refresh_market_metrics,
    upsert_listing,
)
from car_bot.storage.market_reports import SHEET_NAMES, write_market_report


def listing(url, brand="Toyota", model="Corolla", year=2020, price=100000, mileage=100000, photos_count=6):
    return {
        "source": "olx",
        "external_id": url.rsplit("ID", 1)[-1].replace(".html", ""),
        "url": url,
        "title": f"{brand} {model}",
        "brand": brand,
        "model": model,
        "year": year,
        "price": price,
        "currency": "PLN",
        "mileage": mileage,
        "fuel": "Benzyna",
        "gearbox": "Manualna",
        "body_type": "Sedan",
        "engine_cm3": 1600,
        "power_hp": 120,
        "location_city": "Warszawa",
        "location_region": "Mazowieckie",
        "seller_type": "private",
        "photos_count": photos_count,
        "description_len": 120,
        "has_vin_visible": False,
        "has_damage_words": False,
        "has_import_words": False,
        "has_accident_words": False,
        "scraped_at": "2026-05-31T10:00:00+00:00",
    }


class OlxListingsChecks(unittest.TestCase):
    def test_parse_olx_listing_html_keeps_only_safe_public_fields(self):
        html = """
        <html>
          <head>
            <script type="application/ld+json">
            {
              "@context": "https://schema.org",
              "@type": "Vehicle",
              "name": "Toyota Corolla",
              "url": "https://www.olx.pl/d/oferta/toyota-CID5-IDabc.html?search=1",
              "sku": "IDabc",
              "brand": "Toyota",
              "model": "Corolla",
              "productionDate": "2020",
              "description": "Imported car. Do not save text.",
              "seller": {"name": "Private Seller", "email": "seller@example.com"},
              "offers": {
                "price": 80000,
                "priceCurrency": "PLN",
                "areaServed": {"name": "Warszawa, Mazowieckie"}
              },
              "image": ["one.jpg", "two.jpg"]
            }
            </script>
          </head>
          <body>
            <h1>Toyota Corolla</h1>
            <p>Przebieg: 80 000 km</p>
            <p>Rodzaj paliwa: Benzyna</p>
            <p>Skrzynia biegow: Manualna</p>
            <p>Typ nadwozia: Sedan</p>
            <p>Pojemnosc silnika: 1598 cm3</p>
            <p>Moc: 132 KM</p>
            <p>Osoba prywatna</p>
            <section data-testid="ad-description">
              Sprowadzony z Niemiec. VIN visible: WBA3D31060F123456.
            </section>
          </body>
        </html>
        """

        parsed = parse_olx_listing_html(html, "https://www.olx.pl/d/oferta/fallback-CID5-IDx.html")

        self.assertEqual(parsed["external_id"], "IDabc")
        self.assertEqual(parsed["url"], "https://www.olx.pl/d/oferta/toyota-CID5-IDabc.html")
        self.assertEqual(parsed["price"], 80000)
        self.assertEqual(parsed["currency"], "PLN")
        self.assertEqual(parsed["location_city"], "Warszawa")
        self.assertEqual(parsed["location_region"], "Mazowieckie")
        self.assertEqual(parsed["seller_type"], "private")
        self.assertTrue(parsed["has_vin_visible"])
        self.assertTrue(parsed["has_import_words"])
        self.assertNotIn("seller", parsed)
        self.assertNotIn("email", parsed)
        self.assertNotIn("description", parsed)

    def test_parse_olx_listing_html_uses_url_hash_fallback_and_redacts_sensitive_title_text(self):
        url = "https://www.olx.pl/d/oferta/plain-car.html"
        html = """
        <html>
          <body>
            <h1>BMW email test@example.com phone +48 123 456 789 VIN WBA3D31060F123456</h1>
            <p>Przebieg: 90 000 km</p>
          </body>
        </html>
        """

        parsed = parse_olx_listing_html(html, url)

        self.assertEqual(parsed["external_id"], safe_external_id(url, {}))
        self.assertTrue(parsed["external_id"].startswith("url_"))
        self.assertNotIn("test@example.com", parsed["title"])
        self.assertNotIn("+48 123 456 789", parsed["title"])
        self.assertNotIn("WBA3D31060F123456", parsed["title"])

    def test_market_db_tracks_seen_state_metrics_and_daily_counts(self):
        now = "2026-05-31T10:00:00+00:00"
        old = "2026-01-01T10:00:00+00:00"

        with tempfile.TemporaryDirectory() as tmpdir:
            with closing(connect(Path(tmpdir) / "rynek_samochodow.sqlite")) as conn:
                init_market_db(conn)

                old_url = "https://www.olx.pl/d/oferta/toyota-old-CID5-IDold.html"
                cheap_url = "https://www.olx.pl/d/oferta/toyota-cheap-CID5-IDcheap.html"
                bmw_url = "https://www.olx.pl/d/oferta/bmw-CID5-IDbmw.html"

                self.assertEqual(upsert_listing(conn, listing(old_url, price=100000, mileage=130000), old), "new")
                self.assertEqual(upsert_listing(conn, listing(cheap_url, price=70000, mileage=80000), now), "new")
                self.assertEqual(upsert_listing(conn, listing(bmw_url, brand="BMW", model="Seria 3"), now), "new")
                self.assertEqual(upsert_listing(conn, listing(old_url, price=100000, mileage=130000), now), "updated")

                self.assertEqual(mark_missing_inactive(conn, {old_url, cheap_url}), [])
                active_count = conn.execute('SELECT COUNT(*) FROM listings WHERE is_active = 1').fetchone()[0]
                self.assertEqual(active_count, 3)
                disappeared = mark_missing_inactive(conn, {old_url, cheap_url}, complete_snapshot=True)
                refresh_market_metrics(conn, now)
                refresh_daily_brand_counts(conn, now)

                active = fetch_listings(conn, "is_active = 1")
                by_url = {row["url"]: row for row in active}
                cheap = by_url[cheap_url]
                old_row = by_url[old_url]

                self.assertEqual(disappeared, [bmw_url])
                self.assertEqual(old_row["first_seen_at"], old)
                self.assertEqual(old_row["last_seen_at"], now)
                self.assertGreaterEqual(cheap["discount_to_median_percent"], 15)
                self.assertEqual(cheap["is_new_today"], 1)
                self.assertEqual(old_row["is_60_days_old"], 1)
                self.assertEqual(fetch_daily_brand_counts(conn)[0]["brand"], "Toyota")
                self.assertEqual(fetch_daily_brand_counts(conn)[0]["active_count"], 2)

    def test_market_report_writes_expected_sheets(self):
        now = "2026-05-31T10:00:00+00:00"

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rynek_samochodow.sqlite"
            report_path = Path(tmpdir) / "raport_rynku_samochodow.xlsx"
            with closing(connect(db_path)) as conn:
                init_market_db(conn)
                url = "https://www.olx.pl/d/oferta/toyota-CID5-IDone.html"
                upsert_listing(conn, listing(url), now)
                refresh_market_metrics(conn, now)
                refresh_daily_brand_counts(conn, now)
                write_market_report(conn, report_path, disappeared_urls=[])

            workbook = load_workbook(report_path)
            self.assertEqual(
                set(workbook.sheetnames),
                {
                    SHEET_NAMES["daily_brand_counts"],
                    SHEET_NAMES["listings_active"],
                    SHEET_NAMES["new_today"],
                    SHEET_NAMES["disappeared_today"],
                    SHEET_NAMES["cheap_vs_market"],
                    SHEET_NAMES["old_60_plus"],
                    SHEET_NAMES["old_90_plus"],
                },
            )
            headers = [cell.value for cell in workbook[SHEET_NAMES["listings_active"]][1]]
            self.assertIn("zrodlo", headers)
            self.assertIn("id_ogloszenia", headers)
            self.assertIn("tytul", headers)
            self.assertIn("cena", headers)
            self.assertNotIn("source", headers)
            workbook.close()


if __name__ == "__main__":
    unittest.main()
