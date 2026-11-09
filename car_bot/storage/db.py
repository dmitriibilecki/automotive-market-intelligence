import csv
import sqlite3
from pathlib import Path

from car_bot import config
from car_bot.config import FIELDS


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path == config.DB_PATH and not path.exists() and config.LEGACY_DB_PATH.exists():
        config.LEGACY_DB_PATH.rename(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
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
            mileage INTEGER,
            fuel TEXT,
            gearbox TEXT,
            body_type TEXT,
            engine_cm3 INTEGER,
            power_hp INTEGER,
            location TEXT,
            scraped_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(price)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_external_id ON listings(external_id)")
    conn.commit()


def listing_exists(conn: sqlite3.Connection, url: str) -> bool:
    row = conn.execute("SELECT 1 FROM listings WHERE url = ? LIMIT 1", (url,)).fetchone()
    return row is not None


def insert_listing(conn: sqlite3.Connection, listing: dict) -> bool:
    values = {field: listing.get(field) for field in FIELDS}
    placeholders = ", ".join("?" for _ in FIELDS)
    columns = ", ".join(FIELDS)
    cursor = conn.execute(
        f"INSERT OR IGNORE INTO listings ({columns}) VALUES ({placeholders})",
        [values[field] for field in FIELDS],
    )
    conn.commit()
    return cursor.rowcount > 0


def get_all_listings(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        f"SELECT {', '.join(FIELDS)} FROM listings ORDER BY price IS NULL, price ASC"
    ).fetchall()
    return [dict(row) for row in rows]


def export_csv(conn: sqlite3.Connection, csv_path: Path | str) -> None:
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path == config.CSV_PATH and not path.exists() and config.LEGACY_CSV_PATH.exists():
        config.LEGACY_CSV_PATH.rename(path)
    rows = get_all_listings(conn)

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
