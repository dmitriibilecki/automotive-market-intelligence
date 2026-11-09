import json
import random
import re
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from car_bot import config
from car_bot.browser import launch_chromium
from car_bot.storage.db import insert_listing, listing_exists


class StopParsingError(RuntimeError):
    """Raised when OLX appears to block the session."""


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def parse_int(text: str | int | float | None) -> int | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    digits = re.sub(r"\D+", "", text)
    return int(digits) if digits else None


def extract_external_id(url: str, structured_data: dict | None = None) -> str | None:
    if structured_data:
        sku = structured_data.get("sku")
        if sku:
            return str(sku)

    match = re.search(r"-ID([A-Za-z0-9]+)\.html", url)
    if match:
        return f"ID{match.group(1)}"
    return None


def run_olx_parser(
    search_url: str,
    conn,
    max_listings: int = config.MAX_LISTINGS,
    headless: bool = config.HEADLESS,
    min_delay: int = config.MIN_DELAY_SECONDS,
    max_delay: int = config.MAX_DELAY_SECONDS,
) -> dict:
    stats = {"collected_urls": 0, "skipped_existing": 0, "saved": 0, "failed": 0}

    with sync_playwright() as p:
        browser = launch_chromium(p, headless=headless, slow_mo=250)
        context = browser.new_context(
            viewport=config.VIEWPORT,
            user_agent=config.USER_AGENT,
            locale=config.LOCALE,
            permissions=[],
        )
        context.clear_permissions()
        page = context.new_page()

        try:
            urls = collect_listing_urls(page, search_url, max_listings)
            stats["collected_urls"] = len(urls)
            print(f"Zebrane linki ogloszen: {len(urls)}")

            for index, url in enumerate(urls, start=1):
                if listing_exists(conn, url):
                    stats["skipped_existing"] += 1
                    print(f"[{index}/{len(urls)}] Pomijam juz zapisane: {url}")
                    continue

                print(f"[{index}/{len(urls)}] Otwieram ogloszenie: {url}")
                listing_page = context.new_page()
                try:
                    listing = parse_listing_page(listing_page, url)
                    if insert_listing(conn, listing):
                        stats["saved"] += 1
                        print(f"Zapisano: {listing.get('title') or url}")
                except StopParsingError:
                    raise
                except Exception as exc:
                    stats["failed"] += 1
                    print(f"Blad ogloszenia: {url} ({exc})")
                finally:
                    listing_page.close()

                pause(min_delay, max_delay)
        finally:
            context.close()
            browser.close()

    return stats


def collect_listing_urls(page: Page, search_url: str, max_listings: int) -> list[str]:
    response = page.goto(search_url, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT_MS)
    assert_not_blocked(page, response.status if response else None)
    reject_cookies(page)
    close_extra_popups(page)
    pause(2, 4)

    for _ in range(4):
        page.mouse.wheel(0, random.randint(700, 1400))
        pause(1, 2)

    assert_not_blocked(page)
    return extract_listing_urls_from_search_html(page.content(), max_listings)


def collect_listing_urls_across_pages(
    page: Page,
    search_url: str,
    max_pages: int,
    max_listings: int,
) -> tuple[list[str], int]:
    urls: list[str] = []
    seen: set[str] = set()
    pages_processed = 0

    for page_number in range(1, max_pages + 1):
        page_url = build_page_url(search_url, page_number)
        print(f"Strona wyszukiwania {page_number}: otwieram {page_url}")
        response = page.goto(page_url, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT_MS)
        assert_not_blocked(page, response.status if response else None)
        if page_number == 1:
            reject_cookies(page)
        close_extra_popups(page)
        pause(2, 4)

        for scroll_index in range(4):
            print(f"Strona wyszukiwania {page_number}: przewijam {scroll_index + 1}/4")
            page.mouse.wheel(0, random.randint(700, 1400))
            pause(1, 2)

        assert_not_blocked(page)
        page_urls = extract_listing_urls_from_search_html(page.content(), max_listings)
        pages_processed += 1
        print(f"Przetworzona strona wyszukiwania {page_number}: linki ogloszen = {len(page_urls)}")

        if not page_urls:
            if page_number == 1:
                raise RuntimeError("Nie znaleziono kart ogloszen na stronie OLX. Uklad strony mogl sie zmienic.")
            break

        new_on_page = 0
        for url in page_urls:
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
            new_on_page += 1
            if len(urls) >= max_listings:
                return urls, pages_processed

        if new_on_page == 0:
            break

    return urls, pages_processed


def build_page_url(search_url: str, page_number: int) -> str:
    if page_number <= 1:
        return search_url

    parts = urlsplit(search_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["page"] = str(page_number)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def extract_listing_urls_from_search_html(html: str, max_listings: int | None = None) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()

    for card in soup.select('[data-testid="l-card"]'):
        link = card.find("a", href=True)
        if not link:
            continue
        href = str(link["href"])
        add_listing_url(href, urls, seen)
        if max_listings is not None and len(urls) >= max_listings:
            break

    if max_listings is None or len(urls) < max_listings:
        for url in extract_search_json_ld_urls(soup):
            add_listing_url(url, urls, seen)
            if max_listings is not None and len(urls) >= max_listings:
                break

    return urls


def add_listing_url(href: str, urls: list[str], seen: set[str]) -> None:
    if "otomoto" in href.lower() or "/d/oferta/" not in href:
        return

    url = canonicalize_url(urljoin("https://www.olx.pl", href))
    if url in seen:
        return

    seen.add(url)
    urls.append(url)


def extract_search_json_ld_urls(soup: BeautifulSoup) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for candidate in iter_json_ld_candidates(data):
            if not isinstance(candidate, dict):
                continue
            offers = candidate.get("offers")
            for offer in iter_offers(offers):
                url = offer.get("url")
                if not isinstance(url, str):
                    continue
                canonical = canonicalize_url(urljoin("https://www.olx.pl", url))
                if "otomoto" in canonical.lower() or "/d/oferta/" not in canonical:
                    continue
                if canonical in seen:
                    continue
                seen.add(canonical)
                urls.append(canonical)

    return urls


def iter_offers(offers):
    if isinstance(offers, list):
        for item in offers:
            yield from iter_offers(item)
        return

    if not isinstance(offers, dict):
        return

    nested = offers.get("offers")
    if nested:
        yield from iter_offers(nested)
        return

    yield offers


def parse_listing_page(page: Page, url: str) -> dict:
    response = page.goto(url, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT_MS)
    assert_not_blocked(page, response.status if response else None)
    close_extra_popups(page)
    pause(2, 4)
    page.mouse.wheel(0, random.randint(300, 1000))
    pause(1, 2)
    assert_not_blocked(page)
    return parse_listing_html(page.content(), url)


def parse_listing_details_page(page: Page, url: str, snapshot_date: str) -> dict:
    response = page.goto(url, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT_MS)
    assert_not_blocked(page, response.status if response else None)
    close_extra_popups(page)
    pause(2, 4)
    page.mouse.wheel(0, random.randint(300, 1000))
    pause(1, 2)
    assert_not_blocked(page)
    return parse_listing_details_html(page.content(), url, snapshot_date)


def parse_listing_details_html(html: str, url: str, snapshot_date: str) -> dict:
    listing = parse_listing_html(html, url)
    soup = BeautifulSoup(html, "html.parser")
    return {
        "snapshot_date": snapshot_date,
        "source": listing.get("source"),
        "external_id": listing.get("external_id"),
        "url": listing.get("url"),
        "title": listing.get("title"),
        "brand": listing.get("brand"),
        "model": listing.get("model"),
        "year": listing.get("year"),
        "price": listing.get("price"),
        "mileage": listing.get("mileage"),
        "fuel": listing.get("fuel"),
        "gearbox": listing.get("gearbox"),
        "body_type": listing.get("body_type"),
        "engine_cm3": listing.get("engine_cm3"),
        "power_hp": listing.get("power_hp"),
        "location": listing.get("location"),
        "seller_type": extract_seller_type(soup),
    }


def parse_listing_html(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    structured_data = extract_vehicle_json_ld(soup)
    params = extract_vehicle_params(soup)

    offers = structured_data.get("offers") if structured_data else {}
    if not isinstance(offers, dict):
        offers = {}

    area_served = offers.get("areaServed")
    if isinstance(area_served, dict):
        structured_location = area_served.get("name")
    else:
        structured_location = None

    canonical_url = canonicalize_url(structured_data.get("url") or url) if structured_data else canonicalize_url(url)
    title = structured_data.get("name") if structured_data else None

    listing = {
        "source": config.SOURCE,
        "external_id": extract_external_id(canonical_url, structured_data),
        "url": canonical_url,
        "title": clean_text(title) or extract_title(soup),
        "brand": clean_text(structured_data.get("brand") if structured_data else None) or params.get("brand"),
        "model": clean_text(structured_data.get("model") if structured_data else None) or params.get("model"),
        "year": parse_int(structured_data.get("productionDate") if structured_data else None) or parse_int(params.get("year")),
        "price": parse_int(offers.get("price")) or parse_int(params.get("price") or extract_price_text(soup)),
        "mileage": parse_int(params.get("mileage")),
        "fuel": params.get("fuel"),
        "gearbox": params.get("gearbox"),
        "body_type": params.get("body_type"),
        "engine_cm3": parse_int(params.get("engine_cm3")),
        "power_hp": parse_int(params.get("power_hp")),
        "location": clean_text(structured_location) or params.get("location"),
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return {field: listing.get(field) for field in config.FIELDS}


def extract_vehicle_json_ld(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for candidate in iter_json_ld_candidates(data):
            if isinstance(candidate, dict) and candidate.get("@type") == "Vehicle":
                return candidate
    return {}


def iter_json_ld_candidates(data):
    if isinstance(data, list):
        for item in data:
            yield from iter_json_ld_candidates(item)
        return

    if not isinstance(data, dict):
        return

    yield data
    graph = data.get("@graph")
    if graph:
        yield from iter_json_ld_candidates(graph)


def extract_vehicle_params(soup: BeautifulSoup) -> dict:
    text = soup.get_text("\n")
    lines = [clean_text(line) for line in text.split("\n") if clean_text(line)]
    params: dict[str, str] = {}

    label_map = {
        "brand": ("Marka",),
        "model": ("Model", "Model pojazdu", "Model BMW"),
        "year": ("Rok produkcji",),
        "mileage": ("Przebieg",),
        "fuel": ("Paliwo", "Rodzaj paliwa"),
        "gearbox": ("Skrzynia biegów",),
        "body_type": ("Typ nadwozia",),
        "engine_cm3": ("Poj. silnika", "Pojemność silnika"),
        "power_hp": ("Moc silnika", "Moc"),
    }

    for line in lines:
        for field, labels in label_map.items():
            if field in params:
                continue
            value = extract_label_value(line, labels)
            if value:
                params[field] = value

    params["price"] = extract_price_text(soup)
    params["location"] = extract_location(lines)
    return params


def extract_label_value(line: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        pattern = rf"^{re.escape(label)}\s*:\s*(.+)$"
        match = re.search(pattern, line, flags=re.IGNORECASE)
        if match:
            return clean_text(match.group(1))
    return None


def extract_title(soup: BeautifulSoup) -> str:
    heading = soup.find("h1")
    return clean_text(heading.get_text()) if heading else ""


def extract_price_text(soup: BeautifulSoup) -> str:
    price = soup.find(attrs={"data-testid": "ad-price"})
    if price:
        return clean_text(price.get_text())

    text = soup.get_text("\n")
    match = re.search(r"\b\d[\d\s]{2,}\s*zł\b", text, flags=re.IGNORECASE)
    return clean_text(match.group(0)) if match else ""


def extract_location(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if line == "Lokalizacja":
            return lines[index + 1] if index + 1 < len(lines) else ""
    return ""


def extract_seller_type(soup: BeautifulSoup) -> str | None:
    text = soup.get_text("\n")
    lines = [clean_text(line) for line in text.split("\n") if clean_text(line)]
    joined = "\n".join(lines).lower()

    label_map = (
        ("Oferta od",),
        ("Typ sprzedawcy",),
    )
    for line in lines:
        value = extract_label_value(line, tuple(label for labels in label_map for label in labels))
        if value:
            return normalize_seller_type(value)

    if "osoba prywatna" in joined:
        return "private"
    if "firma" in joined or "firmowe" in joined or "dealer" in joined:
        return "company"
    return None


def normalize_seller_type(value: str) -> str:
    lowered = value.lower()
    if "osoba prywatna" in lowered or "prywat" in lowered:
        return "private"
    if "firma" in lowered or "firmowe" in lowered or "dealer" in lowered:
        return "company"
    return clean_text(value)


def reject_cookies(page: Page) -> None:
    button_names = (
        "Odrzucenie wszystkich",
        "Odrzuć wszystkie",
        "Reject all",
        "Nie zgadzam się",
    )
    for name in button_names:
        try:
            page.get_by_role("button", name=name).click(timeout=1500)
            return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue


def reject_cookies(page: Page) -> None:
    reject_selectors = (
        "#onetrust-reject-all-handler",
        "button#onetrust-reject-all-handler",
        "button:has-text('Odrzu\\u0107 wszystkie')",
        "button:has-text('Odrzucenie wszystkich')",
        "button:has-text('Reject all')",
        "button:has-text('Nie zgadzam si\\u0119')",
    )
    for selector in reject_selectors:
        try:
            page.locator(selector).first.click(timeout=2500)
            print("Pliki cookie: odrzucone.")
            page.wait_for_timeout(700)
            return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue

    preference_buttons = (
        "Ustaw preferencje",
        "Zarz\\u0105dzaj opcjami",
        "Manage options",
    )
    reject_buttons = (
        "Odrzu\\u0107 wszystkie",
        "Odrzucenie wszystkich",
        "Reject all",
        "Nie zgadzam si\\u0119",
    )
    for name in preference_buttons:
        try:
            page.get_by_role("button", name=name).click(timeout=2000)
            page.wait_for_timeout(700)
            for reject_name in reject_buttons:
                try:
                    page.get_by_role("button", name=reject_name).click(timeout=2000)
                    print("Pliki cookie: odrzucone w ustawieniach.")
                    page.wait_for_timeout(700)
                    return
                except PlaywrightTimeoutError:
                    continue
                except Exception:
                    continue
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue

    print("Pliki cookie: baner nie jest widoczny albo zostal juz obsluzony.")


def close_extra_popups(page: Page) -> None:
    close_selectors = (
        "button[aria-label='Zamknij']",
        "button[aria-label='Close']",
        "button[title='Zamknij']",
        "button[title='Close']",
        "[data-testid='modal-close']",
        "[data-testid='close-button']",
        "[data-cy='modal-close']",
        "button:has-text('Zamknij')",
        "button:has-text('Nie teraz')",
        "button:has-text('Później')",
        "button:has-text('Pozniej')",
        "button:has-text('Nie, dzięki')",
        "button:has-text('Nie, dzieki')",
        "button:has-text('Nie dziękuję')",
        "button:has-text('Nie dziekuje')",
        "button:has-text('Może później')",
        "button:has-text('Moze pozniej')",
    )

    closed_any = False
    for _ in range(3):
        closed_in_round = False
        for selector in close_selectors:
            try:
                button = page.locator(selector).first
                if button.is_visible(timeout=600):
                    button.click(timeout=1200)
                    page.wait_for_timeout(500)
                    closed_any = True
                    closed_in_round = True
                    break
            except PlaywrightTimeoutError:
                continue
            except Exception:
                continue

        if not closed_in_round:
            break

    if closed_any:
        print("Dodatkowe okno: zamkniete.")


def assert_not_blocked(page: Page, status: int | None = None) -> None:
    if status in config.BLOCK_STATUSES:
        raise StopParsingError(f"OLX zwrocil HTTP {status}; zatrzymuje parser.")

    probe = " ".join((page.url or "", page.title() or "")).lower()
    if any(marker in probe for marker in config.BLOCK_TEXT_MARKERS):
        raise StopParsingError("Wykryto blokade albo captcha OLX; zatrzymuje parser.")

    try:
        body_text = page.locator("body").inner_text(timeout=1500).lower()
    except Exception:
        body_text = ""

    if any(marker in body_text for marker in config.BLOCK_TEXT_MARKERS):
        raise StopParsingError("Wykryto blokade albo captcha OLX w tresci strony; zatrzymuje parser.")


def pause(min_seconds: float, max_seconds: float) -> None:
    time.sleep(random.uniform(min_seconds, max_seconds))
