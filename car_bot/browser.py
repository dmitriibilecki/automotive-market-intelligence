from playwright.sync_api import Error as PlaywrightError


def launch_chromium(playwright, *, headless: bool, slow_mo: int):
    common_args = [
        "--deny-permission-prompts",
        "--disable-geolocation",
    ]
    launch_options = (
        {"channel": "chrome"},
        {"channel": "msedge"},
        {},
    )

    last_error: Exception | None = None
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
        "Playwright nie znalazl dostepnej przegladarki. Zainstaluj Google Chrome albo Microsoft Edge, "
        "albo uruchom: .\\.venv\\Scripts\\python.exe -m playwright install chromium"
    ) from last_error
