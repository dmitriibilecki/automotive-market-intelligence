import argparse
import sys
from pathlib import Path


def configure_console_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


configure_console_output()

from car_bot import config
from car_bot.olx_listings import run_olx_listings
from car_bot.settings_file import apply_settings, detect_cli_overrides, load_settings
from car_bot.warsaw_details import run_warsaw_details
from scripts.olx_marki import run as run_brand_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kolektor danych OLX o samochodach")
    parser.add_argument(
        "--mode",
        choices=("brand_snapshot", "warsaw_details", "olx_listings", "daily_auto", "all"),
        default="brand_snapshot",
        help="Tryb uruchomienia",
    )
    parser.add_argument("--olx-url", default=config.WARSAW_SEARCH_URL, help="Adres wyszukiwania OLX")
    parser.add_argument("--market-db-path", type=Path, default=config.CAR_MARKET_DB_PATH, help="Sciezka do bazy SQLite rynku")
    parser.add_argument("--reports-path", type=Path, default=config.REPORTS_PATH, help="Sciezka do raportu Excel")
    parser.add_argument("--listings-max-pages", type=int, default=config.OLX_LISTINGS_MAX_PAGES, help="Maksymalna liczba stron OLX")
    parser.add_argument("--listings-max-listings", type=int, default=config.OLX_LISTINGS_MAX_LISTINGS, help="Maksymalna liczba ogloszen")
    parser.add_argument("--warsaw-url", default=config.WARSAW_SEARCH_URL, help="Adres wyszukiwania OLX Warszawa")
    parser.add_argument("--warsaw-excel-path", type=Path, default=config.WARSAW_EXCEL_PATH, help="Sciezka do raportu Warszawa")
    parser.add_argument("--max-pages", type=int, default=config.WARSAW_MAX_PAGES, help="Maksymalna liczba stron Warszawa")
    parser.add_argument("--max-listings", type=int, default=config.WARSAW_MAX_LISTINGS, help="Maksymalna liczba ogloszen Warszawa")
    parser.add_argument("--headless", dest="headless", action="store_true", default=True, help="Uruchom przegladarke w tle")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Pokaz okno przegladarki")
    parser.add_argument("--min-delay", type=int, default=config.MIN_DELAY_SECONDS, help="Minimalna przerwa miedzy ogloszeniami")
    parser.add_argument("--max-delay", type=int, default=config.MAX_DELAY_SECONDS, help="Maksymalna przerwa miedzy ogloszeniami")
    args = parser.parse_args()
    args.settings_path = config.OLX_LIMITS_SETTINGS_PATH
    args.loaded_settings = load_settings(args.settings_path)
    apply_settings(args, args.loaded_settings, detect_cli_overrides(sys.argv))
    args.no_args_watch_run = len(sys.argv) == 1
    if args.no_args_watch_run and not args.loaded_settings:
        args.mode = "olx_listings"
        args.olx_url = config.WARSAW_SEARCH_URL
        args.headless = False
        args.listings_max_pages = 1
        args.listings_max_listings = 5
    return args


def main() -> None:
    args = parse_args()
    if args.loaded_settings:
        print(f"Ustawienia: {args.settings_path}")
    if args.no_args_watch_run:
        print("Brak parametrow: uruchamiam wedlug pliku settings/olx_limits.txt.")
        print(
            "Limity: "
            f"tryb={args.mode}, strony={args.listings_max_pages}, "
            f"ogloszenia={args.listings_max_listings}, "
            f"przerwa={args.min_delay}-{args.max_delay}s, "
            f"browser={'w tle' if args.headless else 'widoczny'}."
        )
        print("Uzyj --mode brand_snapshot, aby uruchomic dzienny raport liczby marek.")

    if args.mode == "daily_auto":
        print("Tryb dzienny: etap 1/2 - raport liczby marek.")
        run_brand_snapshot()
        print("\nTryb dzienny: etap 2/2 - pobieranie ogloszen OLX.")
        run_olx_listings(
            search_url=args.olx_url,
            db_path=args.market_db_path,
            report_path=args.reports_path,
            max_pages=args.listings_max_pages,
            max_listings=args.listings_max_listings,
            headless=args.headless,
            min_delay=args.min_delay,
            max_delay=args.max_delay,
        )
        return

    if args.mode in {"brand_snapshot", "all"}:
        run_brand_snapshot()
        if args.mode == "brand_snapshot":
            print(
                "\nGotowe: wykonano tylko raport liczby marek. "
                "Aby pobrac szczegoly ogloszen, uruchom: "
                ".\\.venv\\Scripts\\python.exe .\\main.py --mode olx_listings"
            )

    if args.mode in {"warsaw_details", "all"}:
        run_warsaw_details(
            search_url=args.warsaw_url,
            excel_path=args.warsaw_excel_path,
            max_pages=args.max_pages,
            max_listings=args.max_listings,
            headless=args.headless,
            min_delay=args.min_delay,
            max_delay=args.max_delay,
        )

    if args.mode in {"olx_listings", "all"}:
        run_olx_listings(
            search_url=args.olx_url,
            db_path=args.market_db_path,
            report_path=args.reports_path,
            max_pages=args.listings_max_pages,
            max_listings=args.listings_max_listings,
            headless=args.headless,
            min_delay=args.min_delay,
            max_delay=args.max_delay,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nBLAD: {exc}", file=sys.stderr)
        raise SystemExit(1)
