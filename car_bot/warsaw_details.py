from __future__ import annotations

from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from car_bot import config
from car_bot.browser import launch_chromium
from car_bot.parsers.olx_parser import (
    StopParsingError,
    collect_listing_urls_across_pages,
    parse_listing_details_page,
    pause,
)
from car_bot.storage.warsaw_excel import update_warsaw_excel


def run_warsaw_details(
    search_url: str = config.WARSAW_SEARCH_URL,
    excel_path: Path | str = config.WARSAW_EXCEL_PATH,
    max_pages: int = config.WARSAW_MAX_PAGES,
    max_listings: int = config.WARSAW_MAX_LISTINGS,
    headless: bool = True,
    min_delay: int = config.MIN_DELAY_SECONDS,
    max_delay: int = config.MAX_DELAY_SECONDS,
    snapshot_date: str | None = None,
) -> dict:
    if max_pages < 1:
        raise ValueError("max_pages musi byc co najmniej 1")
    if max_listings < 1:
        raise ValueError("max_listings musi byc co najmniej 1")
    if min_delay < 0 or max_delay < min_delay:
        raise ValueError("max_delay musi byc >= min_delay, a przerwy nie moga byc ujemne")

    snapshot_date = snapshot_date or datetime.now().strftime("%Y-%m-%d")
    parse_stats = {
        "pages_processed": 0,
        "found": 0,
        "parsed": 0,
        "failed": 0,
    }

    with sync_playwright() as p:
        browser = launch_chromium(p, headless=headless, slow_mo=150)
        context = browser.new_context(
            viewport=config.VIEWPORT,
            user_agent=config.USER_AGENT,
            locale=config.LOCALE,
            permissions=[],
        )
        context.clear_permissions()
        search_page = context.new_page()

        try:
            urls, pages_processed = collect_listing_urls_across_pages(
                search_page,
                search_url,
                max_pages=max_pages,
                max_listings=max_listings,
            )
            parse_stats["pages_processed"] = pages_processed
            parse_stats["found"] = len(urls)
            if not urls:
                raise RuntimeError("Nie znaleziono ogloszen OLX dla Warszawy. Uklad strony albo adres mogl sie zmienic.")

            listings = []
            for index, url in enumerate(urls, start=1):
                listing_page = context.new_page()
                try:
                    print(f"[{index}/{len(urls)}] Czytam ogloszenie: {url}")
                    listings.append(parse_listing_details_page(listing_page, url, snapshot_date))
                    parse_stats["parsed"] += 1
                except StopParsingError:
                    raise
                except PlaywrightError as exc:
                    parse_stats["failed"] += 1
                    print(f"Ogloszenie pominiete po bledzie przegladarki: {url} ({exc})")
                except Exception as exc:
                    parse_stats["failed"] += 1
                    print(f"Ogloszenie pominiete po bledzie odczytu: {url} ({exc})")
                finally:
                    listing_page.close()

                pause(min_delay, max_delay)
        finally:
            context.close()
            browser.close()

    save_stats = update_warsaw_excel(listings, snapshot_date=snapshot_date, excel_path=excel_path)
    stats = {**parse_stats, **save_stats}
    print_warsaw_details_stats(stats)
    return stats


def print_warsaw_details_stats(stats: dict) -> None:
    print("\nStatystyki ogloszen Warszawa:")
    print(f"Przetworzone strony: {stats['pages_processed']}")
    print(f"Znalezione ogloszenia: {stats['found']}")
    print(f"Odczytane ogloszenia: {stats['parsed']}")
    print(f"Bledy odczytu ogloszen: {stats['failed']}")
    print(f"Nowe ogloszenia: {stats['new']}")
    print(f"Zaktualizowane ogloszenia: {stats['updated']}")
    print(f"Usuniete ogloszenia: {stats['removed']}")
    print(f"Kandydaci na okazje: {stats['deal_candidates']}")
    print(f"Excel: {stats['excel_path']}")
