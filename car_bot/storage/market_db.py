from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from car_bot import config


LISTING_PUBLIC_FIELDS = [
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
]

LISTING_COLUMNS = LISTING_PUBLIC_FIELDS + [
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path | str = config.CAR_MARKET_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    migrate_legacy_database(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def migrate_legacy_database(path: Path) -> None:
    if path.exists() or path != config.CAR_MARKET_DB_PATH:
        return
    legacy_path = config.LEGACY_CAR_MARKET_DB_PATH
    if legacy_path.exists():
        legacy_path.rename(path)


def init_market_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            external_id TEXT,
            url TEXT NOT NULL UNIQUE,
            title TEXT,
            brand TEXT,
            model TEXT,
            year INTEGER,
            price INTEGER,
            currency TEXT,
            mileage INTEGER,
            fuel TEXT,
            gearbox TEXT,
            body_type TEXT,
            engine_cm3 INTEGER,
            power_hp INTEGER,
            location_city TEXT,
            location_region TEXT,
            seller_type TEXT,
            photos_count INTEGER,
            description_len INTEGER,
            has_vin_visible INTEGER NOT NULL DEFAULT 0,
            has_damage_words INTEGER NOT NULL DEFAULT 0,
            has_import_words INTEGER NOT NULL DEFAULT 0,
            has_accident_words INTEGER NOT NULL DEFAULT 0,
            scraped_at TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            median_price REAL,
            discount_to_median_percent REAL,
            median_mileage REAL,
            days_on_market INTEGER,
            is_new_today INTEGER NOT NULL DEFAULT 0,
            is_60_days_old INTEGER NOT NULL DEFAULT 0,
            is_90_days_old INTEGER NOT NULL DEFAULT 0,
            score INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_brand_counts (
            snapshot_date TEXT NOT NULL,
            brand TEXT NOT NULL,
            active_count INTEGER NOT NULL,
            scraped_at TEXT NOT NULL,
            PRIMARY KEY (snapshot_date, brand)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_market_listings_url ON listings(url)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_market_listings_active ON listings(is_active)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_market_listings_brand_model_year ON listings(brand, model, year)")
    conn.commit()


def upsert_listing(conn: sqlite3.Connection, listing: dict, now: str) -> str:
    existing = conn.execute("SELECT first_seen_at FROM listings WHERE url = ?", (listing["url"],)).fetchone()
    values = normalize_listing_values(listing)
    values["scraped_at"] = now
    values["last_seen_at"] = now
    values["is_active"] = 1

    if existing:
        assignments = ", ".join(f"{field} = ?" for field in LISTING_PUBLIC_FIELDS + ["last_seen_at", "is_active"])
        params = [values.get(field) for field in LISTING_PUBLIC_FIELDS + ["last_seen_at", "is_active"]]
        params.append(listing["url"])
        conn.execute(f"UPDATE listings SET {assignments} WHERE url = ?", params)
        conn.commit()
        return "updated"

    values["first_seen_at"] = now
    insert_fields = LISTING_PUBLIC_FIELDS + ["first_seen_at", "last_seen_at", "is_active"]
    placeholders = ", ".join("?" for _ in insert_fields)
    conn.execute(
        f"INSERT INTO listings ({', '.join(insert_fields)}) VALUES ({placeholders})",
        [values.get(field) for field in insert_fields],
    )
    conn.commit()
    return "new"


def touch_listing_seen(conn: sqlite3.Connection, url: str, now: str) -> bool:
    cursor = conn.execute(
        "UPDATE listings SET last_seen_at = ?, is_active = 1 WHERE url = ?",
        (now, url),
    )
    conn.commit()
    return cursor.rowcount > 0


def mark_missing_inactive(conn: sqlite3.Connection, seen_urls: set[str], *, complete_snapshot: bool = False) -> list[str]:
    """Only infer absence when the caller guarantees full database coverage.

    Capped searches cannot establish that unobserved listings disappeared.
    The inherited live collector deliberately leaves this opt-in disabled.
    """
    if not complete_snapshot:
        return []
    active_rows = conn.execute("SELECT url FROM listings WHERE is_active = 1").fetchall()
    missing_urls = [row["url"] for row in active_rows if row["url"] not in seen_urls]
    if not missing_urls:
        return []

    conn.executemany("UPDATE listings SET is_active = 0 WHERE url = ?", [(url,) for url in missing_urls])
    conn.commit()
    return missing_urls


def refresh_daily_brand_counts(conn: sqlite3.Connection, now: str) -> None:
    snapshot_date = now[:10]
    rows = conn.execute(
        """
        SELECT COALESCE(NULLIF(TRIM(brand), ''), 'unknown') AS brand, COUNT(*) AS active_count
        FROM listings
        WHERE is_active = 1
        GROUP BY COALESCE(NULLIF(TRIM(brand), ''), 'unknown')
        ORDER BY brand
        """
    ).fetchall()
    conn.execute("DELETE FROM daily_brand_counts WHERE snapshot_date = ?", (snapshot_date,))
    conn.executemany(
        """
        INSERT INTO daily_brand_counts (snapshot_date, brand, active_count, scraped_at)
        VALUES (?, ?, ?, ?)
        """,
        [(snapshot_date, row["brand"], row["active_count"], now) for row in rows],
    )
    conn.commit()


def refresh_market_metrics(conn: sqlite3.Connection, now: str) -> None:
    rows = [dict(row) for row in conn.execute("SELECT * FROM listings WHERE is_active = 1").fetchall()]
    groups: dict[tuple[Any, Any, Any], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(norm(row.get("brand")), norm(row.get("model")), row.get("year"))].append(row)

    updates = []
    for row in rows:
        group = groups[(norm(row.get("brand")), norm(row.get("model")), row.get("year"))]
        prices = [to_int(item.get("price")) for item in group if to_int(item.get("price")) is not None]
        mileages = [to_int(item.get("mileage")) for item in group if to_int(item.get("mileage")) is not None]
        median_price = float(median(prices)) if prices else None
        median_mileage = float(median(mileages)) if mileages else None
        discount = discount_percent(row.get("price"), median_price)
        days = days_since(row.get("first_seen_at"), now)
        is_new = is_within_hours(row.get("first_seen_at"), now, 24)
        is_60 = days >= 60
        is_90 = days >= 90
        score = calculate_score(row, median_price, median_mileage, discount, is_new, is_60)
        updates.append(
            (
                median_price,
                discount,
                median_mileage,
                days,
                int(is_new),
                int(is_60),
                int(is_90),
                score,
                row["url"],
            )
        )

    conn.executemany(
        """
        UPDATE listings
        SET median_price = ?,
            discount_to_median_percent = ?,
            median_mileage = ?,
            days_on_market = ?,
            is_new_today = ?,
            is_60_days_old = ?,
            is_90_days_old = ?,
            score = ?
        WHERE url = ?
        """,
        updates,
    )
    conn.commit()


def fetch_listings(conn: sqlite3.Connection, where: str = "", params: tuple = ()) -> list[dict]:
    sql = f"SELECT {', '.join(LISTING_COLUMNS)} FROM listings"
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY score DESC, discount_to_median_percent DESC, price ASC"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def fetch_daily_brand_counts(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT snapshot_date, brand, active_count, scraped_at
            FROM daily_brand_counts
            ORDER BY snapshot_date DESC, active_count DESC, brand ASC
            """
        ).fetchall()
    ]


def fetch_by_urls(conn: sqlite3.Connection, urls: list[str]) -> list[dict]:
    if not urls:
        return []
    placeholders = ", ".join("?" for _ in urls)
    rows = conn.execute(
        f"SELECT {', '.join(LISTING_COLUMNS)} FROM listings WHERE url IN ({placeholders}) ORDER BY brand, model, price",
        urls,
    ).fetchall()
    return [dict(row) for row in rows]


def normalize_listing_values(listing: dict) -> dict:
    values = {field: listing.get(field) for field in LISTING_PUBLIC_FIELDS}
    values["source"] = values.get("source") or config.SOURCE
    values["year"] = to_int(values.get("year"))
    values["price"] = to_int(values.get("price"))
    values["mileage"] = to_int(values.get("mileage"))
    values["engine_cm3"] = to_int(values.get("engine_cm3"))
    values["power_hp"] = to_int(values.get("power_hp"))
    values["photos_count"] = to_int(values.get("photos_count")) or 0
    values["description_len"] = to_int(values.get("description_len")) or 0
    for field in ("has_vin_visible", "has_damage_words", "has_import_words", "has_accident_words"):
        values[field] = int(bool(values.get(field)))
    return values


def calculate_score(
    row: dict,
    median_price: float | None,
    median_mileage: float | None,
    discount: float | None,
    is_new: bool,
    is_60: bool,
) -> int:
    score = 50
    if discount is not None and discount >= 15:
        score += 30
    if is_new:
        score += 10
    mileage = to_int(row.get("mileage"))
    if mileage is not None and median_mileage is not None and mileage < median_mileage:
        score += 15
    if is_60:
        score -= 20
    if row.get("has_damage_words") or row.get("has_import_words") or row.get("has_accident_words"):
        score -= 20
    if (to_int(row.get("photos_count")) or 0) < config.MIN_PHOTOS_FOR_SCORE:
        score -= 10
    return max(0, min(100, score))


def discount_percent(price: Any, median_price: float | None) -> float | None:
    price_int = to_int(price)
    if price_int is None or not median_price:
        return None
    return round((median_price - price_int) / median_price * 100, 2)


def days_since(start: Any, now: str) -> int:
    start_dt = parse_dt(start)
    now_dt = parse_dt(now)
    if not start_dt or not now_dt:
        return 0
    return max((now_dt.date() - start_dt.date()).days, 0)


def is_within_hours(start: Any, now: str, hours: int) -> bool:
    start_dt = parse_dt(start)
    now_dt = parse_dt(now)
    if not start_dt or not now_dt:
        return False
    return 0 <= (now_dt - start_dt).total_seconds() <= hours * 3600


def parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def to_int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def norm(value: Any) -> str:
    return str(value or "").strip().lower()
