from __future__ import annotations

import re
import time
from hashlib import sha256
from contextlib import closing
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

from car_bot import config
from car_bot.browser import launch_chromium
from car_bot.parsers.olx_parser import (
    StopParsingError,
    assert_not_blocked,
    canonicalize_url,
    close_extra_popups,
    clean_text,
    collect_listing_urls_across_pages,
    extract_external_id,
    extract_price_text,
    extract_title,
    extract_vehicle_json_ld,
    extract_vehicle_params,
    parse_int,
    pause,
)
from car_bot.storage.market_db import (
    connect,
    init_market_db,
    mark_missing_inactive,
    refresh_daily_brand_counts,
    refresh_market_metrics,
    touch_listing_seen,
    upsert_listing,
    utc_now,
)
from car_bot.storage.market_reports import write_market_report
from car_bot.storage.run_stats import append_run_stats, average, maximum, minimum, seconds_to_text


VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]*){9,}(?!\d)")
DAMAGE_WORDS = (
    "uszkodz",
    "do naprawy",
    "niesprawny",
    "awaria",
    "szkoda",
    "damaged",
)
IMPORT_WORDS = (
    "import",
    "sprowadz",
    "z niemiec",
    "z holandii",
    "z belgii",
    "z francji",
    "z usa",
    "ze szwajcarii",
)
ACCIDENT_WORDS = (
    "powypad",
    "po wypadku",
    "po kolizji",
    "kolizyj",
    "accident",
)


def run_olx_listings(
    search_url: str = config.DEFAULT_SEARCH_URL,
    db_path: Path | str = config.CAR_MARKET_DB_PATH,
    report_path: Path | str = config.REPORTS_PATH,
    max_pages: int = config.OLX_LISTINGS_MAX_PAGES,
    max_listings: int = config.OLX_LISTINGS_MAX_LISTINGS,
    headless: bool = True,
    min_delay: int = config.MIN_DELAY_SECONDS,
    max_delay: int = config.MAX_DELAY_SECONDS,
) -> dict:
    if max_pages < 1:
        raise ValueError("max_pages musi byc co najmniej 1")
    if max_listings < 1:
        raise ValueError("max_listings musi byc co najmniej 1")
    if min_delay < 0 or max_delay < min_delay:
        raise ValueError("max_delay musi byc >= min_delay, a przerwy nie moga byc ujemne")

    now = utc_now()
    started_perf = time.perf_counter()
    stats = {
        "started_at": now,
        "finished_at": None,
        "duration_seconds": None,
        "pages_processed": 0,
        "found": 0,
        "processed": 0,
        "new": 0,
        "updated": 0,
        "failed": 0,
        "disappeared": 0,
        "search_url": search_url,
        "max_pages": max_pages,
        "max_listings": max_listings,
        "min_delay": min_delay,
        "max_delay": max_delay,
        "headless": headless,
        "listing_seconds": [],
        "avg_listing_seconds": None,
        "min_listing_seconds": None,
        "max_listing_seconds": None,
        "db_path": str(db_path),
        "report_path": str(report_path),
        "run_stats_path": str(config.RUN_STATS_PATH),
    }

    print("Start pobierania ogloszen OLX")
    print(f"Adres wyszukiwania: {search_url}")
    print(f"Baza danych: {db_path}")
    print(f"Raport Excel: {report_path}")
    print(f"Limity: strony={max_pages}, ogloszenia={max_listings}, przerwa={min_delay}-{max_delay}s")
    print("Tryb przegladarki:", "w tle" if headless else "widoczna")

    with closing(connect(db_path)) as conn:
        init_market_db(conn)
        seen_urls: set[str] = set()

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
                stats["pages_processed"] = pages_processed
                stats["found"] = len(urls)
                print(f"Przetworzone strony wyszukiwania: {pages_processed}")
                print(f"Znalezione linki ogloszen: {len(urls)}")
                if len(urls) < max_listings and pages_processed >= max_pages:
                    print(
                        "UWAGA: znaleziono mniej linkow niz limit ogloszen, bo osiagnieto limit stron "
                        f"({pages_processed}/{max_pages}). Zwieksz listings_max_pages, jesli chcesz "
                        f"zebrac blizej {max_listings} ogloszen."
                    )
                if not urls:
                    raise RuntimeError("Nie znaleziono linkow ogloszen OLX; baza nie zostala zmieniona.")

                seen_urls = set(urls)
                listing_page = context.new_page()
                try:
                    print("Czytanie ogloszen: jedna karta przegladarki dla wszystkich ogloszen.")
                    for index, url in enumerate(urls, start=1):
                        listing_started = time.perf_counter()
                        try:
                            print(f"[{index}/{len(urls)}] Czytam ogloszenie: {url}")
                            listing = parse_olx_listing_page(listing_page, url, now)
                            result = upsert_listing(conn, listing, now)
                            stats[result] += 1
                            stats["processed"] += 1
                            print_listing_result(index, len(urls), result, listing)
                        except StopParsingError:
                            raise
                        except PlaywrightError as exc:
                            stats["failed"] += 1
                            touch_listing_seen(conn, url, now)
                            print(f"Ogloszenie pominiete po bledzie przegladarki: {url} ({exc})")
                        except Exception as exc:
                            stats["failed"] += 1
                            touch_listing_seen(conn, url, now)
                            print(f"Ogloszenie pominiete po bledzie odczytu: {url} ({exc})")

                        listing_seconds = round(time.perf_counter() - listing_started, 2)
                        stats["listing_seconds"].append(listing_seconds)
                        print(f"  czas ogloszenia: {seconds_to_text(listing_seconds)}")
                        pause(min_delay, max_delay)
                finally:
                    listing_page.close()
            finally:
                context.close()
                browser.close()

        disappeared_urls = mark_missing_inactive(conn, seen_urls)
        stats["disappeared"] = len(disappeared_urls)
        print(f"Status: oznaczono znikniete ogloszenia: {len(disappeared_urls)}")
        print("Metryki: odswiezam mediane ceny, roznice do rynku, dni na rynku i ocene.")
        refresh_market_metrics(conn, now)
        print("Dzienne liczby marek: odswiezam zrzut.")
        refresh_daily_brand_counts(conn, now)
        print("Raport Excel: zapisuje plik.")
        report_output = write_market_report(conn, report_path, disappeared_urls=disappeared_urls)
        stats["report_path"] = str(report_output)

    finished_at = utc_now()
    stats["finished_at"] = finished_at
    stats["duration_seconds"] = round(time.perf_counter() - started_perf, 2)
    stats["avg_listing_seconds"] = average(stats["listing_seconds"])
    stats["min_listing_seconds"] = minimum(stats["listing_seconds"])
    stats["max_listing_seconds"] = maximum(stats["listing_seconds"])
    stats_path = append_run_stats(build_run_stats_row(stats))
    stats["run_stats_path"] = str(stats_path)
    print_olx_listings_stats(stats)
    return stats


def parse_olx_listing_page(page: Page, url: str, now: str | None = None) -> dict:
    print("  otwieram strone ogloszenia")
    response = page.goto(url, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT_MS)
    assert_not_blocked(page, response.status if response else None)
    close_extra_popups(page)
    pause(2, 4)
    print(f"  tytul strony: {page.title()}")
    print("  przewijam ogloszenie")
    page.mouse.wheel(0, 800)
    pause(1, 2)
    assert_not_blocked(page)
    print("  odczytuje publiczne pola")
    return parse_olx_listing_html(page.content(), url, now=now)


def parse_olx_listing_html(html: str, url: str, now: str | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    structured_data = extract_vehicle_json_ld(soup)
    params = extract_vehicle_params(soup)
    offers = structured_data.get("offers") if structured_data else {}
    if not isinstance(offers, dict):
        offers = {}

    canonical_url = canonicalize_url(structured_data.get("url") or url) if structured_data else canonicalize_url(url)
    price_text = params.get("price") or extract_price_text(soup)
    text = soup.get_text("\n")
    description = extract_description(soup, structured_data)
    location_text = extract_location_text(offers, params)
    city, region = split_location(location_text)

    listing = {
        "source": config.SOURCE,
        "external_id": safe_external_id(canonical_url, structured_data),
        "url": canonical_url,
        "title": sanitize_text(clean_text(structured_data.get("name") if structured_data else None) or extract_title(soup)),
        "brand": clean_text(structured_data.get("brand") if structured_data else None) or params.get("brand"),
        "model": clean_text(structured_data.get("model") if structured_data else None) or params.get("model"),
        "year": parse_int(structured_data.get("productionDate") if structured_data else None) or parse_int(params.get("year")),
        "price": parse_int(offers.get("price")) or parse_int(price_text),
        "currency": extract_currency(offers, price_text),
        "mileage": parse_int(params.get("mileage")),
        "fuel": params.get("fuel"),
        "gearbox": params.get("gearbox"),
        "body_type": params.get("body_type"),
        "engine_cm3": parse_int(params.get("engine_cm3")),
        "power_hp": parse_int(params.get("power_hp")),
        "location_city": city,
        "location_region": region,
        "seller_type": extract_safe_seller_type(soup),
        "photos_count": extract_photos_count(soup, structured_data),
        "description_len": len(description),
        "has_vin_visible": bool(VIN_RE.search(text)),
        "has_damage_words": has_any_word(text, DAMAGE_WORDS),
        "has_import_words": has_any_word(text, IMPORT_WORDS),
        "has_accident_words": has_any_word(text, ACCIDENT_WORDS),
        "scraped_at": now or utc_now(),
    }
    return listing


def safe_external_id(canonical_url: str, structured_data: dict) -> str:
    external_id = extract_external_id(canonical_url, structured_data)
    if external_id:
        return external_id
    return "url_" + sha256(canonical_url.encode("utf-8")).hexdigest()[:16]


def sanitize_text(value: str | None) -> str:
    text = clean_text(value)
    if not text:
        return ""
    text = EMAIL_RE.sub("[email_redacted]", text)
    text = VIN_RE.sub("[vin_redacted]", text)
    text = PHONE_RE.sub("[phone_redacted]", text)
    return clean_text(text)


def extract_currency(offers: dict, price_text: str | None) -> str:
    currency = clean_text(offers.get("priceCurrency"))
    if currency:
        return currency.upper()
    lowered = (price_text or "").lower()
    if "z\u0142" in lowered or "zl" in lowered or "pln" in lowered:
        return "PLN"
    return "PLN"


def extract_location_text(offers: dict, params: dict) -> str:
    area_served = offers.get("areaServed")
    if isinstance(area_served, dict):
        location = clean_text(area_served.get("name"))
        if location:
            return location
    return clean_text(params.get("location"))


def split_location(location: str) -> tuple[str | None, str | None]:
    if not location:
        return None, None
    parts = [clean_text(part) for part in re.split(r"[,;|]", location) if clean_text(part)]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return parts[0], None


def extract_safe_seller_type(soup: BeautifulSoup) -> str:
    text = soup.get_text("\n").lower()
    if "osoba prywatna" in text or "prywat" in text:
        return "private"
    if "firma" in text or "dealer" in text or "firmowe" in text or "przedsi" in text:
        return "business"
    return "unknown"


def extract_photos_count(soup: BeautifulSoup, structured_data: dict) -> int:
    images = structured_data.get("image") if structured_data else None
    if isinstance(images, str):
        structured_count = 1
    elif isinstance(images, list):
        structured_count = len([item for item in images if item])
    else:
        structured_count = 0

    srcs = set()
    for image in soup.find_all("img"):
        src = image.get("src") or image.get("data-src")
        if not src:
            continue
        src_text = str(src)
        if "static" in src_text or src_text.endswith(".svg"):
            continue
        srcs.add(src_text.split("?")[0])
    return max(structured_count, len(srcs))


def extract_description(soup: BeautifulSoup, structured_data: dict) -> str:
    description_node = soup.find(attrs={"data-testid": "ad-description"})
    if description_node:
        return clean_text(description_node.get_text(" "))
    return clean_text(structured_data.get("description") if structured_data else None)


def has_any_word(text: str, words: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)


def print_listing_result(index: int, total: int, result: str, listing: dict) -> None:
    title = listing.get("title") or "no title"
    if len(title) > 80:
        title = title[:77] + "..."
    brand_model = " ".join(part for part in (listing.get("brand"), listing.get("model")) if part) or "unknown model"
    price = listing.get("price") if listing.get("price") is not None else "no price"
    mileage = listing.get("mileage") if listing.get("mileage") is not None else "no mileage"
    print(
        f"[{index}/{total}] zapis={translate_save_result(result)} | {brand_model} | "
        f"rok={listing.get('year') or 'brak'} | cena={price} {listing.get('currency') or ''} | "
        f"przebieg={mileage} | zdjecia={listing.get('photos_count')}"
    )
    print(
        "  flagi: "
        f"vin_widoczny={bool(listing.get('has_vin_visible'))}, "
        f"uszkodzenia={bool(listing.get('has_damage_words'))}, "
        f"import={bool(listing.get('has_import_words'))}, "
        f"wypadek={bool(listing.get('has_accident_words'))}"
    )
    print(f"  tytul: {title}")


def translate_save_result(result: str) -> str:
    return {
        "new": "nowe",
        "updated": "zaktualizowane",
    }.get(result, result)


def print_olx_listings_stats(stats: dict) -> None:
    print("\nPobieranie ogloszen OLX zakonczone")
    print(f"Czas calkowity: {seconds_to_text(stats.get('duration_seconds'))}")
    print(f"Strony wyszukiwania: {stats['pages_processed']}")
    print(f"Znalezione linki: {stats['found']}")
    print(f"Przetworzone ogloszenia: {stats['processed']}")
    print(f"Nowe ogloszenia: {stats['new']}")
    print(f"Zaktualizowane ogloszenia: {stats['updated']}")
    print(f"Znikniete ogloszenia: {stats['disappeared']}")
    print(f"Nieudane ogloszenia: {stats['failed']}")
    print(f"Sredni czas ogloszenia: {seconds_to_text(stats.get('avg_listing_seconds'))}")
    print(f"Najszybsze ogloszenie: {seconds_to_text(stats.get('min_listing_seconds'))}")
    print(f"Najwolniejsze ogloszenie: {seconds_to_text(stats.get('max_listing_seconds'))}")
    print(f"Baza danych: {stats['db_path']}")
    print(f"Raport Excel: {stats['report_path']}")
    print(f"Statystyka uruchomien: {stats['run_stats_path']}")


def build_run_stats_row(stats: dict) -> dict:
    return {
        "mode": "olx_listings",
        "started_at": stats["started_at"],
        "finished_at": stats["finished_at"],
        "duration_seconds": stats["duration_seconds"],
        "pages_processed": stats["pages_processed"],
        "found": stats["found"],
        "processed": stats["processed"],
        "new": stats["new"],
        "updated": stats["updated"],
        "failed": stats["failed"],
        "disappeared": stats["disappeared"],
        "search_url": stats["search_url"],
        "max_pages": stats["max_pages"],
        "max_listings": stats["max_listings"],
        "min_delay": stats["min_delay"],
        "max_delay": stats["max_delay"],
        "headless": stats["headless"],
        "avg_listing_seconds": stats["avg_listing_seconds"],
        "min_listing_seconds": stats["min_listing_seconds"],
        "max_listing_seconds": stats["max_listing_seconds"],
        "db_path": stats["db_path"],
        "report_path": stats["report_path"],
    }
