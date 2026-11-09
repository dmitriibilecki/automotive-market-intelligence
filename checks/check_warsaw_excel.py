import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from car_bot.storage import warsaw_excel
from car_bot.storage.warsaw_excel import update_warsaw_excel


def listing(external_id, price, model="Corolla", year=2020):
    return {
        "snapshot_date": "2026-05-31",
        "source": "olx",
        "external_id": external_id,
        "url": f"https://www.olx.pl/d/oferta/test-CID5-ID{external_id}.html",
        "title": f"Toyota {model}",
        "brand": "Toyota",
        "model": model,
        "year": year,
        "price": price,
        "mileage": 100000,
        "fuel": "Benzyna",
        "gearbox": "Manualna",
        "body_type": "Sedan",
        "engine_cm3": 1600,
        "power_hp": 120,
        "location": "Warszawa",
        "seller_type": "private",
    }


class WarsawExcelChecks(unittest.TestCase):
    def test_update_marks_new_updated_removed_and_writes_sheets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ogloszenia_warszawa.xlsx"

            first_stats = update_warsaw_excel(
                [listing("one", 50000), listing("two", 60000)],
                snapshot_date="2026-05-30",
                excel_path=path,
            )
            second_stats = update_warsaw_excel(
                [listing("one", 49000), listing("three", 61000)],
                snapshot_date="2026-05-31",
                excel_path=path,
            )

            self.assertEqual(first_stats["new"], 2)
            self.assertEqual(second_stats["new"], 1)
            self.assertEqual(second_stats["updated"], 1)
            self.assertEqual(second_stats["removed"], 1)

            workbook = load_workbook(path)
            self.assertEqual(
                set(workbook.sheetnames),
                {
                    warsaw_excel.LISTINGS_SHEET,
                    warsaw_excel.DAILY_SHEET,
                    warsaw_excel.ANALYTICS_SHEET,
                    warsaw_excel.DEALS_SHEET,
                },
            )

            listings_sheet = workbook[warsaw_excel.LISTINGS_SHEET]
            rows = list(listings_sheet.iter_rows(values_only=True))
            headers = [warsaw_excel.REVERSE_COLUMN_LABELS.get(value, value) for value in rows[0]]
            data = [dict(zip(headers, row)) for row in rows[1:]]
            by_key = {row["listing_key"]: row for row in data}

            self.assertEqual(by_key["olx:one"]["price"], 49000)
            self.assertTrue(by_key["olx:one"]["is_active"])
            self.assertFalse(by_key["olx:two"]["is_active"])
            self.assertEqual(by_key["olx:one"]["first_seen_at"], "2026-05-30")
            self.assertEqual(by_key["olx:one"]["last_seen_at"], "2026-05-31")

    def test_deal_candidates_require_five_similar_listings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ogloszenia_warszawa.xlsx"
            rows = [
                listing("cheap", 80000),
                listing("a", 100000),
                listing("b", 101000),
                listing("c", 102000),
                listing("d", 103000),
                listing("e", 104000),
                listing("f", 105000),
            ]

            stats = update_warsaw_excel(rows, snapshot_date="2026-05-31", excel_path=path)

            self.assertEqual(stats["deal_candidates"], 1)
            workbook = load_workbook(path)
            deals = list(workbook[warsaw_excel.DEALS_SHEET].iter_rows(values_only=True))
            self.assertEqual(deals[1][0], "olx:cheap")
            self.assertGreaterEqual(deals[1][12], 15)


if __name__ == "__main__":
    unittest.main()
