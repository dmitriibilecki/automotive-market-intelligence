import argparse
from pathlib import Path

from car_bot import config
from car_bot.analysis.market import analyze_market, print_report
from car_bot.parsers.olx_parser import StopParsingError, run_olx_parser
from car_bot.storage.db import connect, export_csv, get_all_listings, init_db


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parser cen samochodow OLX MVP")
    parser.add_argument("--search-url", default=config.DEFAULT_SEARCH_URL, help="Adres wyszukiwania OLX")
    parser.add_argument("--max-listings", type=int, default=config.MAX_LISTINGS, help="Maksymalna liczba linkow ogloszen")
    parser.add_argument("--db-path", type=Path, default=config.DB_PATH, help="Sciezka do bazy SQLite")
    parser.add_argument("--csv-path", type=Path, default=config.CSV_PATH, help="Sciezka eksportu CSV")
    parser.add_argument("--headless", action="store_true", help="Uruchom przegladarke w tle")
    parser.add_argument("--no-headless", action="store_true", help="Pokaz okno przegladarki")
    parser.add_argument("--analyze-only", action="store_true", help="Nie pobieraj danych; tylko eksportuj i analizuj zapisane dane")
    parser.add_argument("--min-delay", type=int, default=config.MIN_DELAY_SECONDS, help="Minimalna przerwa miedzy ogloszeniami")
    parser.add_argument("--max-delay", type=int, default=config.MAX_DELAY_SECONDS, help="Maksymalna przerwa miedzy ogloszeniami")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    headless = config.HEADLESS
    if args.headless:
        headless = True
    if args.no_headless:
        headless = False
    if args.min_delay < 0 or args.max_delay < args.min_delay:
        raise SystemExit("--max-delay musi byc >= --min-delay, a przerwy nie moga byc ujemne")

    with connect(args.db_path) as conn:
        init_db(conn)

        if not args.analyze_only:
            try:
                stats = run_olx_parser(
                    search_url=args.search_url,
                    conn=conn,
                    max_listings=args.max_listings,
                    headless=headless,
                    min_delay=args.min_delay,
                    max_delay=args.max_delay,
                )
                print(
                    "\nStatystyki parsera: "
                    f"urls={stats['collected_urls']}, "
                    f"pominiete_juz_istniejace={stats['skipped_existing']}, "
                    f"zapisane={stats['saved']}, "
                    f"nieudane={stats['failed']}"
                )
            except StopParsingError as exc:
                print(f"\nZatrzymano bezpiecznie: {exc}")

        export_csv(conn, args.csv_path)
        print(f"CSV wyeksportowany: {args.csv_path}")

        listings = get_all_listings(conn)
        print_report(analyze_market(listings))


if __name__ == "__main__":
    main()
