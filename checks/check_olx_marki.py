import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from scripts import olx_marki


class OlxMarkiExcelChecks(unittest.TestCase):
    def test_save_counts_adds_one_column_per_report_date(self):
        original_data_dir = olx_marki.DATA_DIR
        original_excel_file = olx_marki.EXCEL_FILE

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                olx_marki.DATA_DIR = Path(tmpdir)
                olx_marki.EXCEL_FILE = Path(tmpdir) / "raport_ilosci_marek.xlsx"

                first_counts = {brand: index for index, brand in enumerate(olx_marki.BRANDS, 1)}
                second_counts = {brand: index * 10 for index, brand in enumerate(olx_marki.BRANDS, 1)}

                olx_marki.save_counts_to_excel(first_counts, report_date="2026-05-29")
                olx_marki.save_counts_to_excel(second_counts, report_date="2026-05-29")
                olx_marki.save_counts_to_excel(first_counts, report_date="2026-05-30")

                workbook = load_workbook(olx_marki.EXCEL_FILE)
                sheet = workbook.active

                self.assertEqual(
                    [sheet.cell(row=1, column=col).value for col in range(1, sheet.max_column + 1)],
                    ["Marka", "2026-05-29", "2026-05-30"],
                )
                self.assertEqual(sheet.max_column, 3)
                self.assertEqual(sheet.cell(row=2, column=1).value, "Audi")
                self.assertEqual(sheet.cell(row=2, column=2).value, second_counts["Audi"])
                self.assertEqual(sheet.cell(row=2, column=3).value, first_counts["Audi"])
                self.assertIn("Jaguar", [sheet.cell(row=row, column=1).value for row in range(2, sheet.max_row + 1)])
        finally:
            olx_marki.DATA_DIR = original_data_dir
            olx_marki.EXCEL_FILE = original_excel_file

    def test_save_counts_by_sheet_writes_main_and_warsaw_sheets(self):
        original_data_dir = olx_marki.DATA_DIR
        original_excel_file = olx_marki.EXCEL_FILE

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                olx_marki.DATA_DIR = Path(tmpdir)
                olx_marki.EXCEL_FILE = Path(tmpdir) / "raport_ilosci_marek.xlsx"

                main_counts = {brand: index for index, brand in enumerate(olx_marki.BRANDS, 1)}
                warsaw_counts = {brand: index * 100 for index, brand in enumerate(olx_marki.BRANDS, 1)}

                olx_marki.save_counts_by_sheet(
                    {
                        olx_marki.MAIN_SHEET: main_counts,
                        olx_marki.WARSAW_SHEET: warsaw_counts,
                    },
                    report_date="2026-05-31",
                )

                workbook = load_workbook(olx_marki.EXCEL_FILE)

                self.assertEqual(workbook.sheetnames, [olx_marki.MAIN_SHEET, olx_marki.WARSAW_SHEET])
                self.assertEqual(workbook[olx_marki.MAIN_SHEET]["A1"].value, "Marka")
                self.assertEqual(workbook[olx_marki.WARSAW_SHEET]["A1"].value, "Marka")

                jaguar_row = olx_marki.BRANDS.index("Jaguar") + 2
                self.assertEqual(workbook[olx_marki.MAIN_SHEET].cell(row=jaguar_row, column=2).value, main_counts["Jaguar"])
                self.assertEqual(
                    workbook[olx_marki.WARSAW_SHEET].cell(row=jaguar_row, column=2).value,
                    warsaw_counts["Jaguar"],
                )
        finally:
            olx_marki.DATA_DIR = original_data_dir
            olx_marki.EXCEL_FILE = original_excel_file

    def test_save_counts_by_sheet_renames_legacy_sheets(self):
        original_data_dir = olx_marki.DATA_DIR
        original_excel_file = olx_marki.EXCEL_FILE

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                olx_marki.DATA_DIR = Path(tmpdir)
                olx_marki.EXCEL_FILE = Path(tmpdir) / "raport_ilosci_marek.xlsx"

                olx_marki.save_counts_to_excel(
                    {brand: index for index, brand in enumerate(olx_marki.BRANDS, 1)},
                    report_date="2026-05-30",
                    sheet_name="marki",
                )
                olx_marki.save_counts_to_excel(
                    {brand: index * 10 for index, brand in enumerate(olx_marki.BRANDS, 1)},
                    report_date="2026-05-30",
                    sheet_name="warsaw_scree",
                )

                olx_marki.save_counts_by_sheet(
                    {
                        olx_marki.MAIN_SHEET: {brand: index * 100 for index, brand in enumerate(olx_marki.BRANDS, 1)},
                        olx_marki.WARSAW_SHEET: {
                            brand: index * 1000 for index, brand in enumerate(olx_marki.BRANDS, 1)
                        },
                    },
                    report_date="2026-05-31",
                )

                workbook = load_workbook(olx_marki.EXCEL_FILE)

                self.assertEqual(workbook.sheetnames, [olx_marki.MAIN_SHEET, olx_marki.WARSAW_SHEET])
                self.assertEqual(workbook[olx_marki.MAIN_SHEET]["B1"].value, "2026-05-30")
                self.assertEqual(workbook[olx_marki.MAIN_SHEET]["C1"].value, "2026-05-31")
                self.assertEqual(workbook[olx_marki.WARSAW_SHEET]["B1"].value, "2026-05-30")
                self.assertEqual(workbook[olx_marki.WARSAW_SHEET]["C1"].value, "2026-05-31")
        finally:
            olx_marki.DATA_DIR = original_data_dir
            olx_marki.EXCEL_FILE = original_excel_file


if __name__ == "__main__":
    unittest.main()
