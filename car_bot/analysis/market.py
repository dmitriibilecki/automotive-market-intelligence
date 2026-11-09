from statistics import mean, median


def percentile(values: list[int], percent: float) -> float | None:
    if not values:
        return None

    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])

    rank = (len(ordered) - 1) * percent
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def analyze_market(listings: list[dict]) -> dict:
    priced = [int(item["price"]) for item in listings if item.get("price")]
    p25 = percentile(priced, 0.25)
    p10 = percentile(priced, 0.10)

    cheap = [
        item for item in listings
        if item.get("price") is not None and p25 is not None and int(item["price"]) < p25
    ]
    very_cheap = [
        item for item in listings
        if item.get("price") is not None and p10 is not None and int(item["price"]) < p10
    ]

    return {
        "count": len(listings),
        "priced_count": len(priced),
        "min_price": min(priced) if priced else None,
        "median_price": median(priced) if priced else None,
        "avg_price": mean(priced) if priced else None,
        "p25": p25,
        "p10": p10,
        "cheap": cheap,
        "very_cheap": very_cheap,
    }


def format_money(value: float | int | None) -> str:
    if value is None:
        return "brak"
    return f"{round(value):,} PLN".replace(",", " ")


def print_report(report: dict) -> None:
    print("\n=== Raport rynku ===")
    print(f"Ogloszenia: {report['count']}")
    print(f"Ogloszenia z cena: {report['priced_count']}")
    print(f"Minimalna cena: {format_money(report['min_price'])}")
    print(f"Mediana ceny: {format_money(report['median_price'])}")
    print(f"Srednia cena: {format_money(report['avg_price'])}")
    print(f"P25: {format_money(report['p25'])}")
    print(f"P10: {format_money(report['p10'])}")

    _print_deals("Tanie ogloszenia ponizej P25", report["cheap"])
    _print_deals("Bardzo tanie ogloszenia ponizej P10", report["very_cheap"])


def _print_deals(title: str, listings: list[dict], limit: int = 20) -> None:
    print(f"\n{title}: {len(listings)}")
    for item in sorted(listings, key=lambda x: x.get("price") or 0)[:limit]:
        year = item.get("year") or "?"
        mileage = item.get("mileage")
        mileage_text = f", {mileage:,} km".replace(",", " ") if mileage else ""
        print(
            f"- {format_money(item.get('price'))} | {item.get('title') or 'brak tytulu'} "
            f"({year}{mileage_text}) | {item.get('url')}"
        )
