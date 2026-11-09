import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data" / "marki_dane"
EXCEL_FILE = DATA_DIR / "raport_ilosci_marek.xlsx"

OLX_URL = "https://www.olx.pl/motoryzacja/samochody/"
WARSAW_OLX_URL = "https://www.olx.pl/motoryzacja/samochody/warszawa/"
MAIN_SHEET = "marki_ilosc_polska"
WARSAW_SHEET = "marki_ilosc_warszawa"
LEGACY_SHEET_NAMES = {
    "marki": MAIN_SHEET,
    "warsaw_scree": WARSAW_SHEET,
}

BRANDS = [
    "Audi",
    "BMW",
    "Mercedes-Benz",
    "Porsche",
    "Opel",
    "Volkswagen",
    "Skoda",
    "Volvo",
    "Toyota",
    "Honda",
    "Hyundai",
    "Nissan",
    "Mitsubishi",
    "Subaru",
    "Suzuki",
    "Kia",
    "Lexus",
    "Citroen",
    "Peugeot",
    "Ford",
    "Jaguar",
    "Jeep",
]

BLOCK_MARKERS = [
    "captcha",
    "access denied",
    "too many requests",
    "sprawdz, czy nie jestes robotem",
    "sprawdz, czy nie jesteś robotem",
    "verify you are human",
]

NETWORK_DENIED_HINT = (
    "Przegladarka nie ma dostepu do sieci (ERR_NETWORK_ACCESS_DENIED). "
    "Plik Excel nie zostal zaktualizowany. Sprawdz Windows Firewall albo antywirusa dla Playwright Chromium."
)


def human_pause(min_sec=1.5, max_sec=4.0):
    time.sleep(random.uniform(min_sec, max_sec))


def launch_chromium(playwright, headless=True, slow_mo=100):
    common_args = [
        "--deny-permission-prompts",
        "--disable-geolocation",
    ]
    launch_options = (
        {"channel": "chrome"},
        {"channel": "msedge"},
        {},
    )

    last_error = None
    for options in launch_options:
        try:
            return playwright.chromium.launch(
                headless=headless,
                slow_mo=slow_mo,
                args=common_args,
                **options,
            )
        except PlaywrightError as exc:
            last_error = exc
            message = str(exc)
            missing_browser = (
                "Executable doesn't exist" in message
                or "Chromium distribution" in message
                or "not found" in message.lower()
            )
            if not missing_browser:
                raise

    raise RuntimeError(
        "Playwright nie znalazl przegladarki. Zainstaluj Google Chrome/Microsoft Edge "
        "albo uruchom: .\\.venv\\Scripts\\python.exe -m playwright install chromium"
    ) from last_error


def clean_text(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def normalize_count(value):
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def reject_cookies(page):
    reject_selectors = (
        "#onetrust-reject-all-handler",
        "button#onetrust-reject-all-handler",
        "button:has-text('Odrzu\\u0107 wszystkie')",
        "button:has-text('Odrzucenie wszystkich')",
        "button:has-text('Reject all')",
    )
    for selector in reject_selectors:
        try:
            page.locator(selector).first.click(timeout=3000)
            print("Pliki cookie: odrzucone.")
            human_pause(1.0, 2.0)
            return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue

    print("Pliki cookie: baner nie jest widoczny albo zostal juz obsluzony.")


def close_extra_popups(page):
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
                if button.is_visible(timeout=800):
                    button.click(timeout=1500)
                    closed_any = True
                    closed_in_round = True
                    human_pause(0.5, 1.0)
                    break
            except PlaywrightTimeoutError:
                continue
            except Exception:
                continue

        if not closed_in_round:
            break

    if closed_any:
        print("Dodatkowe okno: zamkniete.")


def stop_if_blocked(page, response):
    status = response.status if response else None
    if status in (403, 429):
        raise RuntimeError(f"OLX zwrocil HTTP {status}. Plik Excel nie zostal zaktualizowany.")

    body_text = page.locator("body").inner_text(timeout=10000).lower()
    if any(marker in body_text for marker in BLOCK_MARKERS):
        raise RuntimeError("OLX pokazal captcha albo blokade. Plik Excel nie zostal zaktualizowany.")


def open_full_brand_list(page):
    selectors = (
        "text=Poka\\u017c wszystkie",
        "text=Poka\\u017c wi\\u0119cej",
        "text=Pokaż wszystkie",
        "text=Pokaż więcej",
    )
    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=5000)
            human_pause(1.5, 2.5)
            return
        except PlaywrightTimeoutError:
            continue
    raise RuntimeError("Nie znaleziono przycisku do rozwiniecia listy marek.")


def parse_brand_counts(page_text):
    counts = {}

    for raw_line in page_text.splitlines():
        line = clean_text(raw_line)

        for brand in BRANDS:
            match = re.fullmatch(rf"{re.escape(brand)}\s*([0-9][0-9 ]*)", line)
            if match:
                counts[brand] = normalize_count(match.group(1))

    return counts


def collect_counts_from_olx(search_url=OLX_URL, label="OLX"):
    with sync_playwright() as p:
        browser = launch_chromium(p, headless=True, slow_mo=100)
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="pl-PL",
            permissions=[],
        )
        context.clear_permissions()

        page = context.new_page()
        print(f"Zrzut: {label} - {search_url}")

        try:
            print("Otwieram OLX...")
            try:
                response = page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
            except Exception as exc:
                if "ERR_NETWORK_ACCESS_DENIED" in str(exc):
                    raise RuntimeError(NETWORK_DENIED_HINT) from exc
                raise
            human_pause(2, 4)

            reject_cookies(page)
            human_pause(2, 4)
            close_extra_popups(page)
            stop_if_blocked(page, response)

            print("Otwieram pelna liste marek...")
            open_full_brand_list(page)
            close_extra_popups(page)
            stop_if_blocked(page, response)

            text = page.locator("body").inner_text(timeout=10000)
            counts = parse_brand_counts(text)

            missing = [brand for brand in BRANDS if brand not in counts]
            if missing:
                raise RuntimeError("Nie znaleziono marek na stronie OLX: " + ", ".join(missing))

            return counts

        finally:
            context.close()
            browser.close()


def find_or_create_date_column(sheet, report_date):
    for col in range(2, sheet.max_column + 1):
        if str(sheet.cell(row=1, column=col).value) == report_date:
            return col

    col = sheet.max_column + 1
    sheet.cell(row=1, column=col, value=report_date)
    return col


def find_or_create_brand_row(sheet, brand):
    for row in range(2, sheet.max_row + 1):
        if sheet.cell(row=row, column=1).value == brand:
            return row

    row = sheet.max_row + 1
    sheet.cell(row=row, column=1, value=brand)
    return row


def migrate_legacy_sheet_names(workbook):
    for old_name, new_name in LEGACY_SHEET_NAMES.items():
        if old_name in workbook.sheetnames and new_name not in workbook.sheetnames:
            workbook[old_name].title = new_name


def get_or_create_sheet(workbook, sheet_name):
    if sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
    elif workbook.sheetnames == ["Sheet"] and workbook["Sheet"].max_row == 1 and workbook["Sheet"].max_column == 1:
        sheet = workbook["Sheet"]
        sheet.title = sheet_name
    else:
        sheet = workbook.create_sheet(sheet_name)

    if sheet.cell(row=1, column=1).value is None:
        sheet.cell(row=1, column=1, value="Marka")

    return sheet


def fill_counts_sheet(sheet, counts, report_date):
    date_col = find_or_create_date_column(sheet, report_date)

    for brand in BRANDS:
        row = find_or_create_brand_row(sheet, brand)
        sheet.cell(row=row, column=date_col, value=counts.get(brand))

    sort_counts_sheet(sheet)
    sheet.freeze_panes = "B2"
    sheet.column_dimensions["A"].width = 20
    for col in range(2, sheet.max_column + 1):
        sheet.column_dimensions[sheet.cell(row=1, column=col).column_letter].width = 14


def sort_counts_sheet(sheet):
    max_column = sheet.max_column
    rows_by_brand = {}
    extra_rows = []
    for row_index in range(2, sheet.max_row + 1):
        values = [sheet.cell(row=row_index, column=col).value for col in range(1, max_column + 1)]
        brand = values[0]
        if brand in BRANDS and brand not in rows_by_brand:
            rows_by_brand[brand] = values
        elif any(value is not None for value in values):
            extra_rows.append(values)

    sorted_rows = [rows_by_brand.get(brand, [brand] + [None] * (max_column - 1)) for brand in BRANDS]
    sorted_rows.extend(extra_rows)

    for row_index in range(2, sheet.max_row + 1):
        for col in range(1, max_column + 1):
            sheet.cell(row=row_index, column=col, value=None)

    for row_offset, values in enumerate(sorted_rows, start=2):
        for col, value in enumerate(values, start=1):
            sheet.cell(row=row_offset, column=col, value=value)


def save_counts_to_excel(counts, report_date=None, sheet_name=MAIN_SHEET):
    return save_counts_by_sheet({sheet_name: counts}, report_date=report_date)


def save_counts_by_sheet(counts_by_sheet, report_date=None):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    migrate_legacy_excel_file()
    report_date = report_date or datetime.now().strftime("%Y-%m-%d")

    if EXCEL_FILE.exists():
        workbook = load_workbook(EXCEL_FILE)
    else:
        workbook = Workbook()

    migrate_legacy_sheet_names(workbook)

    for sheet_name, counts in counts_by_sheet.items():
        sheet = get_or_create_sheet(workbook, sheet_name)
        fill_counts_sheet(sheet, counts, report_date)

    try:
        workbook.save(EXCEL_FILE)
    except PermissionError as exc:
        raise RuntimeError(
            f"Nie moge zapisac {EXCEL_FILE}. Zamknij ten plik Excel i uruchom ponownie."
        ) from exc

    return EXCEL_FILE


def migrate_legacy_excel_file():
    if EXCEL_FILE.exists():
        return
    legacy_file = DATA_DIR / "marki_raport.xlsx"
    if legacy_file.exists():
        try:
            legacy_file.rename(EXCEL_FILE)
        except PermissionError as exc:
            raise RuntimeError(
                f"Nie moge zmienic nazwy {legacy_file} na {EXCEL_FILE}. Zamknij ten plik Excel i uruchom ponownie."
            ) from exc


def run():
    snapshots = {
        MAIN_SHEET: collect_counts_from_olx(OLX_URL, "OLX Polska"),
        WARSAW_SHEET: collect_counts_from_olx(WARSAW_OLX_URL, "OLX Warszawa"),
    }
    output = save_counts_by_sheet(snapshots)

    print("\nGotowe.")
    print(f"Excel: {output}")
    for sheet_name, counts in snapshots.items():
        print(f"\n{sheet_name}:")
        for brand in BRANDS:
            print(f"{brand}: {counts.get(brand, '')}")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"\nBLAD: {exc}", file=sys.stderr)
        raise SystemExit(1)
