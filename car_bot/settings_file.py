from __future__ import annotations

from pathlib import Path
from typing import Any

from car_bot import config


BOOLEAN_TRUE = {"1", "true", "yes", "y", "tak", "да", "on"}
BOOLEAN_FALSE = {"0", "false", "no", "n", "nie", "нет", "off"}

SETTING_TYPES = {
    "mode": str,
    "olx_url": str,
    "listings_max_pages": int,
    "listings_max_listings": int,
    "headless": bool,
    "min_delay": int,
    "max_delay": int,
    "warsaw_url": str,
    "max_pages": int,
    "max_listings": int,
}

MODE_CHOICES = {"brand_snapshot", "warsaw_details", "olx_listings", "daily_auto", "all"}


def load_settings(path: Path | str = config.OLX_LIMITS_SETTINGS_PATH) -> dict[str, Any]:
    settings_path = Path(path)
    if not settings_path.exists():
        return {}

    values: dict[str, Any] = {}
    for line_number, raw_line in enumerate(settings_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{settings_path}:{line_number}: строка должна быть в формате ключ=значение")

        key, value = [part.strip() for part in line.split("=", 1)]
        if key not in SETTING_TYPES:
            raise ValueError(f"{settings_path}:{line_number}: неизвестная настройка '{key}'")
        values[key] = parse_value(key, value, settings_path, line_number)

    return values


def parse_value(key: str, value: str, path: Path, line_number: int) -> Any:
    expected_type = SETTING_TYPES[key]
    if expected_type is bool:
        lowered = value.lower()
        if lowered in BOOLEAN_TRUE:
            return True
        if lowered in BOOLEAN_FALSE:
            return False
        raise ValueError(f"{path}:{line_number}: для {key} используй true/false")

    if expected_type is int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: для {key} нужно целое число") from exc
        if parsed < 0:
            raise ValueError(f"{path}:{line_number}: для {key} нельзя ставить отрицательное число")
        return parsed

    if key == "mode" and value not in MODE_CHOICES:
        raise ValueError(f"{path}:{line_number}: mode должен быть одним из {', '.join(sorted(MODE_CHOICES))}")

    return value


def apply_settings(args, settings: dict[str, Any], cli_overrides: set[str]) -> None:
    for key, value in settings.items():
        if key in cli_overrides:
            continue
        setattr(args, key, value)


def detect_cli_overrides(argv: list[str]) -> set[str]:
    option_to_dest = {
        "--mode": "mode",
        "--olx-url": "olx_url",
        "--market-db-path": "market_db_path",
        "--reports-path": "reports_path",
        "--listings-max-pages": "listings_max_pages",
        "--listings-max-listings": "listings_max_listings",
        "--warsaw-url": "warsaw_url",
        "--warsaw-excel-path": "warsaw_excel_path",
        "--max-pages": "max_pages",
        "--max-listings": "max_listings",
        "--headless": "headless",
        "--no-headless": "headless",
        "--min-delay": "min_delay",
        "--max-delay": "max_delay",
    }
    overrides: set[str] = set()
    for item in argv[1:]:
        option = item.split("=", 1)[0]
        dest = option_to_dest.get(option)
        if dest:
            overrides.add(dest)
    return overrides
