from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

from car_bot import config


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 2)


def minimum(values: list[float]) -> float | None:
    if not values:
        return None
    return round(min(values), 2)


def maximum(values: list[float]) -> float | None:
    if not values:
        return None
    return round(max(values), 2)


def append_run_stats(row: dict[str, Any], path: Path | str = config.RUN_STATS_PATH) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return output


def seconds_to_text(seconds: float | int | None) -> str:
    if seconds is None:
        return "brak danych"
    total = int(round(float(seconds)))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {sec}s"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"
