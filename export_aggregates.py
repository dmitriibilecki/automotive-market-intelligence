"""Export a narrow aggregate view, never individual listings or seller fields."""
import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from statistics import median

BRANDS = {'BMW', 'Volkswagen', 'Audi', 'Opel', 'Mercedes-Benz', 'Ford', 'Toyota',
          'Skoda', 'Renault', 'Peugeot', 'Hyundai', 'Kia', 'Honda', 'Volvo', 'Nissan'}
MIN_GROUP_SIZE = 20


def export(database, output):
    database = Path(database).resolve()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    groups = defaultdict(list)
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as conn:
        total = conn.execute('SELECT COUNT(*) FROM listings').fetchone()[0]
        observed_from, observed_to = conn.execute('SELECT MIN(first_seen_at), MAX(last_seen_at) FROM listings').fetchone()
        # No titles, URLs, IDs, descriptions, images, locations or seller fields.
        for brand, year, price, mileage in conn.execute('SELECT brand, year, price, mileage FROM listings WHERE currency = ? AND price > 0', ('PLN',)):
            if brand not in BRANDS or type(year) is not int or not 1980 <= year <= 2026:
                continue
            if type(price) not in (int, float) or not 1000 <= price <= 2000000:
                continue
            groups[(brand, year)].append((price, mileage))
    rows = []
    for (brand, year), values in sorted(groups.items()):
        if len(values) < MIN_GROUP_SIZE:
            continue
        mileages = [m for _, m in values if type(m) in (int, float) and 0 <= m <= 1000000]
        rows.append({'data_kind': 'observed_archive_aggregate', 'brand': brand, 'year': year,
                     'listing_count': len(values), 'median_asking_price_pln': median(p for p, _ in values),
                     'median_mileage_km': median(mileages) if len(mileages) >= MIN_GROUP_SIZE else '',
                     'mileage_observation_count': len(mileages)})
    if not rows:
        raise ValueError('No groups meet the publication threshold.')
    with (output / 'observed_brand_year.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata = {'data_kind': 'observed_archive_aggregate', 'source': 'Personal vehicle-listing observation archive',
                'archive_record_count': total, 'archive_observed_from_utc': observed_from, 'archive_observed_to_utc': observed_to,
                'minimum_group_size': MIN_GROUP_SIZE, 'published_groups': len(rows),
                'published_listing_observations': sum(r['listing_count'] for r in rows),
                'unit': 'One stored listing URL; relistings may describe the same vehicle',
                'limitations': ['Convenience sample; no market representativeness claimed.',
                                'Each stored listing contributes its last observed asking price across the archive window.',
                                'This is neither a point-in-time inventory nor a transaction-price series.',
                                'Active flags are excluded because crawl coverage was not validated.',
                                'The aggregate table is not a model-training dataset or a valuation benchmark.']}
    (output / 'observed_metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print('Published aggregate groups:', len(rows), '| Contributing observations:', metadata['published_listing_observations'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent / 'examples')
    args = parser.parse_args()
    export(args.database, args.output)
