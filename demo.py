"""Reproducible synthetic market demo; no network or original listing data."""
import csv
import html
import json
import random
import sqlite3
from pathlib import Path
from statistics import median
from car_bot.storage.market_db import init_market_db, upsert_listing, refresh_market_metrics, refresh_daily_brand_counts, fetch_listings

ROOT = Path(__file__).resolve().parent

def main():
    output = ROOT / 'output'
    output.mkdir(exist_ok=True)
    rng = random.Random(42)
    now = '2026-01-15T12:00:00+00:00'
    brands = [('Toyota', 'Corolla', 74000), ('Skoda', 'Octavia', 68000), ('Ford', 'Focus', 53000), ('BMW', '320', 88000), ('Audi', 'A4', 92000), ('Volkswagen', 'Golf', 65000)]
    with sqlite3.connect(output / 'synthetic_market.sqlite') as conn:
        conn.row_factory = sqlite3.Row
        init_market_db(conn)
        for b, (brand, model, base) in enumerate(brands):
            for n in range(40):
                listing = {'source': 'synthetic', 'external_id': f'demo-{b}-{n}',
                           'url': f'https://example.invalid/vehicle/{b}/{n}', 'title': f'{brand} {model} — synthetic fixture',
                           'brand': brand, 'model': model, 'year': 2019 + n % 3,
                           'price': int(base * rng.uniform(.72, 1.28)), 'currency': 'PLN',
                           'mileage': rng.randrange(45000, 210000, 1000), 'fuel': 'Petrol',
                           'gearbox': 'Automatic' if n % 2 else 'Manual', 'location_city': 'Demo City',
                           'photos_count': 8, 'description_len': 200}
                upsert_listing(conn, listing, now)
        refresh_market_metrics(conn, now)
        refresh_daily_brand_counts(conn, now)
        listings = fetch_listings(conn)
    summary = []
    for brand, _, _ in brands:
        rows = [x for x in listings if x['brand'] == brand]
        summary.append({'data_kind': 'synthetic', 'brand': brand, 'listing_count': len(rows),
                        'median_asking_price_pln': median(x['price'] for x in rows),
                        'median_mileage_km': median(x['mileage'] for x in rows)})
    with (output / 'brand_summary.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    (output / 'summary.json').write_text(json.dumps({'data_kind': 'synthetic', 'records': len(listings), 'brands': summary}, indent=2), encoding='utf-8')
    table = ''.join('<tr><td>' + html.escape(x['brand']) + '</td><td>' + str(x['listing_count']) + '</td><td>' + f"{x['median_asking_price_pln']:,.0f}" + '</td><td>' + f"{x['median_mileage_km']:,.0f}" + '</td></tr>' for x in summary)
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><title>Automotive Market Intelligence | Synthetic demo</title><style>body{font:17px system-ui;background:#101f2b;color:#eef4f6;max-width:1050px;margin:55px auto;padding:24px}h1{font-size:44px}table{border-collapse:collapse;width:100%;background:#19303e}td,th{text-align:left;padding:18px;border-bottom:1px solid #344d5b}.accent{color:#62d9bb}small{color:#b6cad3}</style><p class="accent">AUTOMOTIVE MARKET INTELLIGENCE / SYNTHETIC DEMO</p><h1>Compare listings with context.</h1><p>240 fictional vehicles · 6 brands · reproducible SQLite pipeline</p><h2>Asking-price overview</h2><table><tr><th>Brand</th><th>Listings</th><th>Median price, PLN</th><th>Median mileage, km</th></tr>' + table + '</table><p><small>Synthetic demonstration only. Asking prices are not transaction prices. These figures do not estimate the real Polish market.</small></p></html>'
    (output / 'market.html').write_text(page, encoding='utf-8')
    print('Synthetic demo complete:', len(listings), 'records; output/market.html and output/brand_summary.csv')

if __name__ == '__main__':
    main()
