from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook

from car_bot import config
from car_bot.storage.market_db import fetch_by_urls, fetch_daily_brand_counts, fetch_listings


REPORT_COLUMNS = [
    "source",
    "external_id",
    "url",
    "title",
    "brand",
    "model",
    "year",
    "price",
    "currency",
    "mileage",
    "fuel",
    "gearbox",
    "body_type",
    "engine_cm3",
    "power_hp",
    "location_city",
    "location_region",
    "seller_type",
    "photos_count",
    "description_len",
    "has_vin_visible",
    "has_damage_words",
    "has_import_words",
    "has_accident_words",
    "scraped_at",
    "first_seen_at",
    "last_seen_at",
    "is_active",
    "median_price",
    "discount_to_median_percent",
    "median_mileage",
    "days_on_market",
    "is_new_today",
    "is_60_days_old",
    "is_90_days_old",
    "score",
]

DAILY_COLUMNS = ["snapshot_date", "brand", "active_count", "scraped_at"]
COLUMN_LABELS = {
    "source": "zrodlo",
    "external_id": "id_ogloszenia",
    "url": "link",
    "title": "tytul",
    "brand": "marka",
    "model": "model",
    "year": "rok",
    "price": "cena",
    "currency": "waluta",
    "mileage": "przebieg",
    "fuel": "paliwo",
    "gearbox": "skrzynia_biegow",
    "body_type": "typ_nadwozia",
    "engine_cm3": "pojemnosc_silnika_cm3",
    "power_hp": "moc_km",
    "location_city": "miasto",
    "location_region": "wojewodztwo",
    "seller_type": "typ_sprzedawcy",
    "photos_count": "liczba_zdjec",
    "description_len": "dlugosc_opisu",
    "has_vin_visible": "czy_vin_widoczny",
    "has_damage_words": "slowa_uszkodzenia",
    "has_import_words": "slowa_importu",
    "has_accident_words": "slowa_wypadku",
    "scraped_at": "pobrano_o",
    "first_seen_at": "pierwszy_raz_widziane",
    "last_seen_at": "ostatni_raz_widziane",
    "is_active": "czy_aktywne",
    "median_price": "mediana_ceny",
    "discount_to_median_percent": "roznica_do_mediany_proc",
    "median_mileage": "mediana_przebiegu",
    "days_on_market": "dni_na_rynku",
    "is_new_today": "czy_nowe_dzisiaj",
    "is_60_days_old": "czy_60_dni",
    "is_90_days_old": "czy_90_dni",
    "score": "ocena",
    "snapshot_date": "data_zrzutu",
    "active_count": "liczba_aktywnych",
}
SHEET_NAMES = {
    "daily_brand_counts": "dzienne_liczby_marek",
    "listings_active": "aktywne_ogloszenia",
    "new_today": "nowe_dzisiaj",
    "disappeared_today": "zniknely_dzisiaj",
    "cheap_vs_market": "tansze_od_rynku",
    "old_60_plus": "starsze_60_dni",
    "old_90_plus": "starsze_90_dni",
}
BOOLEAN_COLUMNS = {
    "has_vin_visible",
    "has_damage_words",
    "has_import_words",
    "has_accident_words",
    "is_active",
    "is_new_today",
    "is_60_days_old",
    "is_90_days_old",
}


def write_market_report(conn, report_path: Path | str = config.REPORTS_PATH, disappeared_urls: list[str] | None = None) -> Path:
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    migrate_legacy_report_file(path)
    disappeared_urls = disappeared_urls or []

    sheets = {
        SHEET_NAMES["daily_brand_counts"]: (DAILY_COLUMNS, fetch_daily_brand_counts(conn)),
        SHEET_NAMES["listings_active"]: (REPORT_COLUMNS, fetch_listings(conn, "is_active = 1")),
        SHEET_NAMES["new_today"]: (REPORT_COLUMNS, fetch_listings(conn, "is_active = 1 AND is_new_today = 1")),
        SHEET_NAMES["disappeared_today"]: (REPORT_COLUMNS, fetch_by_urls(conn, disappeared_urls)),
        SHEET_NAMES["cheap_vs_market"]: (
            REPORT_COLUMNS,
            fetch_listings(conn, "is_active = 1 AND discount_to_median_percent >= 15"),
        ),
        SHEET_NAMES["old_60_plus"]: (REPORT_COLUMNS, fetch_listings(conn, "is_active = 1 AND is_60_days_old = 1")),
        SHEET_NAMES["old_90_plus"]: (REPORT_COLUMNS, fetch_listings(conn, "is_active = 1 AND is_90_days_old = 1")),
    }

    workbook = Workbook()
    default = workbook.active
    workbook.remove(default)

    for sheet_name, (columns, rows) in sheets.items():
        write_sheet(workbook, sheet_name, columns, rows)

    try:
        workbook.save(path)
    except PermissionError as exc:
        raise RuntimeError(f"Nie moge zapisac {path}. Zamknij ten plik Excel i uruchom ponownie.") from exc
    return path


def migrate_legacy_report_file(path: Path) -> None:
    if path.exists() or path != config.REPORTS_PATH:
        return
    legacy_path = config.LEGACY_REPORTS_PATH
    if legacy_path.exists():
        legacy_path.rename(path)


def write_sheet(workbook: Workbook, sheet_name: str, columns: list[str], rows: list[dict]) -> None:
    sheet = workbook.create_sheet(sheet_name)
    sheet.append([COLUMN_LABELS.get(column, column) for column in columns])
    for row in rows:
        sheet.append([excel_value(row.get(column), column) for column in columns])
    sheet.freeze_panes = "A2"
    for column_cells in sheet.columns:
        letter = column_cells[0].column_letter
        max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
        sheet.column_dimensions[letter].width = min(max(max_length + 2, 12), 55)


def excel_value(value: Any, column: str) -> Any:
    if column in BOOLEAN_COLUMNS and value in (0, 1, True, False):
        return bool(value)
    return value
