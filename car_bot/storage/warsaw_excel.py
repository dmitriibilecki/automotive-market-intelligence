from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from openpyxl import Workbook, load_workbook

from car_bot import config
from car_bot.parsers.olx_parser import canonicalize_url


LISTINGS_SHEET = "ogloszenia"
DAILY_SHEET = "dzienne_zrzuty"
ANALYTICS_SHEET = "analityka_dzienna"
DEALS_SHEET = "kandydaci_okazje"
LEGACY_SHEET_NAMES = {
    "listings": LISTINGS_SHEET,
    "daily_snapshots": DAILY_SHEET,
    "analytics_daily": ANALYTICS_SHEET,
    "deal_candidates": DEALS_SHEET,
}

LISTINGS_COLUMNS = [
    "listing_key",
    "snapshot_date",
    "source",
    "external_id",
    "url",
    "title",
    "brand",
    "model",
    "year",
    "price",
    "mileage",
    "fuel",
    "gearbox",
    "body_type",
    "engine_cm3",
    "power_hp",
    "location",
    "seller_type",
    "first_seen_at",
    "last_seen_at",
    "is_active",
]

DAILY_COLUMNS = [
    "snapshot_date",
    "listing_key",
    "price",
    "mileage",
    "is_active_now",
]

ANALYTICS_COLUMNS = [
    "snapshot_date",
    "scope",
    "brand",
    "model",
    "total_active_listings",
    "new_listings_count",
    "removed_listings_count",
    "active_count",
    "new_count",
    "removed_count",
    "avg_price",
    "median_price",
    "min_price",
    "max_price",
]

DEAL_COLUMNS = [
    "listing_key",
    "snapshot_date",
    "brand",
    "model",
    "year",
    "price",
    "mileage",
    "fuel",
    "gearbox",
    "location",
    "url",
    "market_median_price",
    "discount_percent",
    "days_on_market",
    "deal_score",
]

DETAIL_FIELDS = [
    "snapshot_date",
    "source",
    "external_id",
    "url",
    "title",
    "brand",
    "model",
    "year",
    "price",
    "mileage",
    "fuel",
    "gearbox",
    "body_type",
    "engine_cm3",
    "power_hp",
    "location",
    "seller_type",
]

COLUMN_LABELS = {
    "listing_key": "klucz_ogloszenia",
    "snapshot_date": "data_zrzutu",
    "source": "zrodlo",
    "external_id": "id_ogloszenia",
    "url": "link",
    "title": "tytul",
    "brand": "marka",
    "model": "model",
    "year": "rok",
    "price": "cena",
    "mileage": "przebieg",
    "fuel": "paliwo",
    "gearbox": "skrzynia_biegow",
    "body_type": "typ_nadwozia",
    "engine_cm3": "pojemnosc_silnika_cm3",
    "power_hp": "moc_km",
    "location": "lokalizacja",
    "seller_type": "typ_sprzedawcy",
    "first_seen_at": "pierwszy_raz_widziane",
    "last_seen_at": "ostatni_raz_widziane",
    "is_active": "czy_aktywne",
    "is_active_now": "czy_aktywne_teraz",
    "scope": "zakres",
    "total_active_listings": "liczba_aktywnych_razem",
    "new_listings_count": "liczba_nowych_ogloszen",
    "removed_listings_count": "liczba_usunietych_ogloszen",
    "active_count": "liczba_aktywnych",
    "new_count": "liczba_nowych",
    "removed_count": "liczba_usunietych",
    "avg_price": "srednia_cena",
    "median_price": "mediana_ceny",
    "min_price": "minimalna_cena",
    "max_price": "maksymalna_cena",
    "market_median_price": "mediana_ceny_rynku",
    "discount_percent": "roznica_do_rynku_proc",
    "days_on_market": "dni_na_rynku",
    "deal_score": "ocena_okazji",
}
REVERSE_COLUMN_LABELS = {value: key for key, value in COLUMN_LABELS.items()}


def update_warsaw_excel(listings: list[dict], snapshot_date: str, excel_path: Path | str) -> dict:
    path = Path(excel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    migrate_legacy_warsaw_file(path)

    workbook = load_or_create_workbook(path)
    migrate_legacy_sheet_names(workbook)
    existing_rows = read_sheet(workbook, LISTINGS_SHEET)
    existing_by_key = {
        str(row["listing_key"]): row
        for row in existing_rows
        if row.get("listing_key")
    }

    current_by_key: dict[str, dict] = {}
    for listing in listings:
        key = make_listing_key(listing)
        if not key:
            continue
        normalized = normalize_listing(listing, snapshot_date, key)
        current_by_key[key] = normalized

    previous_active_keys = {
        key
        for key, row in existing_by_key.items()
        if bool_value(row.get("is_active"))
    }
    current_keys = set(current_by_key)
    new_keys = current_keys - set(existing_by_key)
    updated_keys = current_keys & set(existing_by_key)
    removed_keys = previous_active_keys - current_keys

    master_by_key = dict(existing_by_key)
    for key, listing in current_by_key.items():
        if key in master_by_key:
            row = dict(master_by_key[key])
            first_seen_at = row.get("first_seen_at") or snapshot_date
            for field in DETAIL_FIELDS:
                row[field] = listing.get(field)
            row["listing_key"] = key
            row["first_seen_at"] = first_seen_at
            row["last_seen_at"] = snapshot_date
            row["is_active"] = True
            master_by_key[key] = row
        else:
            row = {column: None for column in LISTINGS_COLUMNS}
            for field in DETAIL_FIELDS:
                row[field] = listing.get(field)
            row["listing_key"] = key
            row["first_seen_at"] = snapshot_date
            row["last_seen_at"] = snapshot_date
            row["is_active"] = True
            master_by_key[key] = row

    for key in removed_keys:
        row = dict(master_by_key[key])
        row["is_active"] = False
        row["last_seen_at"] = snapshot_date
        master_by_key[key] = row

    master_rows = sorted(master_by_key.values(), key=lambda row: str(row.get("listing_key") or ""))
    previous_daily_rows = read_sheet(workbook, DAILY_SHEET)
    daily_rows = previous_daily_rows + make_daily_rows(master_by_key, current_keys, removed_keys, snapshot_date)
    analytics_rows = replace_snapshot_rows(
        read_sheet(workbook, ANALYTICS_SHEET),
        snapshot_date,
        make_analytics_rows(master_by_key, new_keys, removed_keys, snapshot_date),
    )
    deal_rows = make_deal_rows(master_by_key, snapshot_date)

    write_sheet(workbook, LISTINGS_SHEET, LISTINGS_COLUMNS, master_rows)
    write_sheet(workbook, DAILY_SHEET, DAILY_COLUMNS, daily_rows)
    write_sheet(workbook, ANALYTICS_SHEET, ANALYTICS_COLUMNS, analytics_rows)
    write_sheet(workbook, DEALS_SHEET, DEAL_COLUMNS, deal_rows)

    try:
        workbook.save(path)
    except PermissionError as exc:
        raise RuntimeError(f"Cannot save {path}. Close the Excel file and run again.") from exc

    return {
        "excel_path": str(path),
        "new": len(new_keys),
        "updated": len(updated_keys),
        "removed": len(removed_keys),
        "deal_candidates": len(deal_rows),
    }


def migrate_legacy_warsaw_file(path: Path) -> None:
    if path.exists() or path != config.WARSAW_EXCEL_PATH:
        return
    legacy_path = config.LEGACY_WARSAW_EXCEL_PATH
    if legacy_path.exists():
        legacy_path.rename(path)


def load_or_create_workbook(path: Path) -> Workbook:
    if path.exists():
        return load_workbook(path)
    workbook = Workbook()
    default = workbook.active
    workbook.remove(default)
    return workbook


def migrate_legacy_sheet_names(workbook: Workbook) -> None:
    for old_name, new_name in LEGACY_SHEET_NAMES.items():
        if old_name in workbook.sheetnames and new_name not in workbook.sheetnames:
            workbook[old_name].title = new_name


def read_sheet(workbook: Workbook, sheet_name: str) -> list[dict]:
    if sheet_name not in workbook.sheetnames:
        return []

    sheet = workbook[sheet_name]
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [
        REVERSE_COLUMN_LABELS.get(str(value), str(value)) if value is not None else ""
        for value in rows[0]
    ]
    records: list[dict] = []
    for row in rows[1:]:
        if not any(cell is not None for cell in row):
            continue
        records.append({headers[index]: row[index] if index < len(row) else None for index in range(len(headers))})
    return records


def write_sheet(workbook: Workbook, sheet_name: str, columns: list[str], rows: list[dict]) -> None:
    if sheet_name in workbook.sheetnames:
        del workbook[sheet_name]
    sheet = workbook.create_sheet(sheet_name)
    sheet.append([COLUMN_LABELS.get(column, column) for column in columns])
    for row in rows:
        sheet.append([row.get(column) for column in columns])
    sheet.freeze_panes = "A2"
    for column_cells in sheet.columns:
        letter = column_cells[0].column_letter
        max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
        sheet.column_dimensions[letter].width = min(max(max_length + 2, 12), 45)


def make_listing_key(listing: dict) -> str | None:
    source = clean_str(listing.get("source")) or "olx"
    external_id = clean_str(listing.get("external_id"))
    if external_id:
        return f"{source}:{external_id}"

    url = clean_str(listing.get("url"))
    if not url:
        return None
    return f"{source}:url:{canonicalize_url(url)}"


def normalize_listing(listing: dict, snapshot_date: str, listing_key: str) -> dict:
    row = {field: listing.get(field) for field in DETAIL_FIELDS}
    row["listing_key"] = listing_key
    row["snapshot_date"] = snapshot_date
    row["source"] = clean_str(row.get("source")) or "olx"
    row["url"] = canonicalize_url(clean_str(row.get("url"))) if clean_str(row.get("url")) else None
    row["price"] = to_int(row.get("price"))
    row["mileage"] = to_int(row.get("mileage"))
    row["year"] = to_int(row.get("year"))
    row["engine_cm3"] = to_int(row.get("engine_cm3"))
    row["power_hp"] = to_int(row.get("power_hp"))
    return row


def make_daily_rows(
    master_by_key: dict[str, dict],
    current_keys: set[str],
    removed_keys: set[str],
    snapshot_date: str,
) -> list[dict]:
    rows = []
    for key in sorted(current_keys | removed_keys):
        listing = master_by_key[key]
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "listing_key": key,
                "price": listing.get("price"),
                "mileage": listing.get("mileage"),
                "is_active_now": key in current_keys,
            }
        )
    return rows


def make_analytics_rows(
    master_by_key: dict[str, dict],
    new_keys: set[str],
    removed_keys: set[str],
    snapshot_date: str,
) -> list[dict]:
    active_rows = [row for row in master_by_key.values() if bool_value(row.get("is_active"))]
    priced = [to_int(row.get("price")) for row in active_rows if to_int(row.get("price")) is not None]
    rows = [
        {
            "snapshot_date": snapshot_date,
            "scope": "razem",
            "brand": None,
            "model": None,
            "total_active_listings": len(active_rows),
            "new_listings_count": len(new_keys),
            "removed_listings_count": len(removed_keys),
            "active_count": len(active_rows),
            "new_count": len(new_keys),
            "removed_count": len(removed_keys),
            "avg_price": avg(priced),
            "median_price": med(priced),
            "min_price": min(priced) if priced else None,
            "max_price": max(priced) if priced else None,
        }
    ]

    groups: set[tuple[Any, Any]] = set()
    for row in active_rows:
        groups.add((row.get("brand"), row.get("model")))
    for key in new_keys | removed_keys:
        row = master_by_key.get(key, {})
        groups.add((row.get("brand"), row.get("model")))

    for brand, model in sorted(groups, key=lambda item: (str(item[0] or ""), str(item[1] or ""))):
        group_active = [
            row
            for row in active_rows
            if row.get("brand") == brand and row.get("model") == model
        ]
        group_prices = [to_int(row.get("price")) for row in group_active if to_int(row.get("price")) is not None]
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "scope": "marka_model",
                "brand": brand,
                "model": model,
                "total_active_listings": None,
                "new_listings_count": None,
                "removed_listings_count": None,
                "active_count": len(group_active),
                "new_count": count_keys_for_group(master_by_key, new_keys, brand, model),
                "removed_count": count_keys_for_group(master_by_key, removed_keys, brand, model),
                "avg_price": avg(group_prices),
                "median_price": med(group_prices),
                "min_price": min(group_prices) if group_prices else None,
                "max_price": max(group_prices) if group_prices else None,
            }
        )
    return rows


def replace_snapshot_rows(existing_rows: list[dict], snapshot_date: str, new_rows: list[dict]) -> list[dict]:
    return [row for row in existing_rows if str(row.get("snapshot_date")) != snapshot_date] + new_rows


def make_deal_rows(master_by_key: dict[str, dict], snapshot_date: str) -> list[dict]:
    active = [
        row
        for row in master_by_key.values()
        if bool_value(row.get("is_active")) and to_int(row.get("price")) is not None
    ]
    by_market: dict[tuple[Any, Any, Any, Any], list[dict]] = defaultdict(list)
    for row in active:
        by_market[market_key(row)].append(row)

    deals = []
    for row in active:
        market_rows = [item for item in by_market[market_key(row)] if item.get("listing_key") != row.get("listing_key")]
        close_year_rows = close_year_matches(row, market_rows)
        comparison_rows = close_year_rows if len(close_year_rows) >= 5 else market_rows
        if len(comparison_rows) < 5:
            continue

        prices = [to_int(item.get("price")) for item in comparison_rows if to_int(item.get("price")) is not None]
        if len(prices) < 5:
            continue

        market_median = med(prices)
        price = to_int(row.get("price"))
        if not market_median or price is None:
            continue

        discount_percent = (market_median - price) / market_median * 100
        if discount_percent < 15:
            continue

        days_on_market = days_between(row.get("first_seen_at"), row.get("last_seen_at"))
        deal_score = discount_percent - min(days_on_market, 90) * 0.1
        deals.append(
            {
                "listing_key": row.get("listing_key"),
                "snapshot_date": snapshot_date,
                "brand": row.get("brand"),
                "model": row.get("model"),
                "year": row.get("year"),
                "price": price,
                "mileage": row.get("mileage"),
                "fuel": row.get("fuel"),
                "gearbox": row.get("gearbox"),
                "location": row.get("location"),
                "url": row.get("url"),
                "market_median_price": round(market_median, 2),
                "discount_percent": round(discount_percent, 2),
                "days_on_market": days_on_market,
                "deal_score": round(deal_score, 2),
            }
        )
    return sorted(deals, key=lambda item: item["deal_score"], reverse=True)


def market_key(row: dict) -> tuple[Any, Any, Any, Any]:
    return (
        normalize_group_value(row.get("brand")),
        normalize_group_value(row.get("model")),
        normalize_group_value(row.get("fuel")),
        normalize_group_value(row.get("gearbox")),
    )


def close_year_matches(row: dict, market_rows: list[dict]) -> list[dict]:
    year = to_int(row.get("year"))
    if year is None:
        return []
    return [item for item in market_rows if to_int(item.get("year")) is not None and abs(to_int(item.get("year")) - year) <= 2]


def count_keys_for_group(master_by_key: dict[str, dict], keys: set[str], brand: Any, model: Any) -> int:
    return sum(
        1
        for key in keys
        if master_by_key.get(key, {}).get("brand") == brand
        and master_by_key.get(key, {}).get("model") == model
    )


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "tak"}


def to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def clean_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def normalize_group_value(value: Any) -> str:
    return clean_str(value).lower()


def avg(values: list[int]) -> float | None:
    return round(mean(values), 2) if values else None


def med(values: list[int]) -> float | None:
    return float(median(values)) if values else None


def days_between(start: Any, end: Any) -> int:
    start_date = parse_date(start)
    end_date = parse_date(end)
    if not start_date or not end_date:
        return 0
    return max((end_date - start_date).days, 0)


def parse_date(value: Any):
    if isinstance(value, datetime):
        return value.date()
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None
