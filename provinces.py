# provinces.py — Province → city lists and weekly rotation schedule (stdlib only).

from __future__ import annotations

from datetime import date

PROVINCE_CITIES: dict[str, list[str]] = {
    "Ontario": [
        "Toronto, Ontario",
        "Mississauga, Ontario",
        "Brampton, Ontario",
        "Ottawa, Ontario",
        "Scarborough, Ontario",
        "North York, Ontario",
        "Hamilton, Ontario",
        "London, Ontario",
        "Markham, Ontario",
        "Vaughan, Ontario",
        "Pickering, Ontario",
        "Kingston, Ontario",  
        "Waterloo, Ontario",
        "Guelph, Ontario",
        "Kitchener, Ontario",
        "Cambridge, Ontario",
        "Barrie, Ontario",
        "Oshawa, Ontario",
        "Thunder Bay, Ontario",
        "Niagara Falls, Ontario",
        "St. Thomas, Ontario",
        "Sarnia, Ontario",
        "Windsor, Ontario",
        "Sault Ste. Marie, Ontario",
        "Gatineau, Ontario",
        "Sherbrooke, Ontario",
    ],
    "Quebec": [
        "Montreal, Quebec",
        "Quebec City, Quebec",
        "Laval, Quebec",
        "Longueuil, Quebec",
    ],
    "Alberta": [
        "Calgary, Alberta",
        "Edmonton, Alberta",
        "Red Deer, Alberta",
        "Lethbridge, Alberta",
    ],
    "British Columbia": [
        "Vancouver, British Columbia",
        "Surrey, British Columbia",
        "Burnaby, British Columbia",
        "Richmond, British Columbia",
        "Abbotsford, British Columbia",
    ],
    "Manitoba": ["Winnipeg, Manitoba", "Brandon, Manitoba"],
    "Saskatchewan": ["Saskatoon, Saskatchewan", "Regina, Saskatchewan"],
    "Nova Scotia": ["Halifax, Nova Scotia", "Dartmouth, Nova Scotia"],
    "New Brunswick": [
        "Moncton, New Brunswick",
        "Saint John, New Brunswick",
        "Fredericton, New Brunswick",
        
    ],
    "Prince Edward Island": ["Charlottetown, Prince Edward Island"],
    "Newfoundland": ["St. John's, Newfoundland"],
}

PROVINCE_ROTATION: list[str] = [
    "Ontario",
    "Quebec",
    "Alberta",
    "British Columbia",
    "Manitoba",
    "Saskatchewan",
    "Nova Scotia",
    "New Brunswick",
    "Prince Edward Island",
    "Newfoundland",
]

MINUTES_PER_CITY = 8


def _normalize_province_key(province: str) -> str | None:
    """Match province name case-insensitively to PROVINCE_CITIES keys."""
    needle = province.strip().lower()
    for key in PROVINCE_CITIES:
        if key.lower() == needle:
            return key
    return None


def get_province_for_week(week_number: int | None = None) -> str:
    """
    Return province for given ISO week number (defaults to current week).
    Formula: PROVINCE_ROTATION[(week_number - 1) % len(PROVINCE_ROTATION)]
    Week 1 → Ontario, Week 2 → Quebec, ... Week 11 → Ontario again.
    """
    if week_number is None:
        week_number = date.today().isocalendar()[1]
    index = (week_number - 1) % len(PROVINCE_ROTATION)
    return PROVINCE_ROTATION[index]


def get_cities_for_province(province: str) -> list[str]:
    """Return city list for province. Empty list if province not found."""
    key = _normalize_province_key(province)
    if key is None:
        return []
    return list(PROVINCE_CITIES[key])


def get_rotation_schedule() -> list[dict]:
    """
    Return full schedule as list of dicts with keys:
    rotation_slot, province, cities, city_count,
    estimated_tasks (= city_count), estimated_minutes (= city_count * 8)
    """
    rows: list[dict] = []
    for slot, province in enumerate(PROVINCE_ROTATION, start=1):
        cities = PROVINCE_CITIES[province]
        city_count = len(cities)
        rows.append(
            {
                "rotation_slot": slot,
                "province": province,
                "cities": cities,
                "city_count": city_count,
                "estimated_tasks": city_count,
                "estimated_minutes": city_count * MINUTES_PER_CITY,
            }
        )
    return rows


def print_schedule() -> None:
    """
    Print formatted rotation table to stdout:
    - Header: current week number and which province it maps to
    - Table columns: Slot | Province | Cities | Est. time
    - Mark current week's province with ◄ THIS WEEK
    - Footer: total provinces, total cities, full cycle length in weeks
    """
    current_week = date.today().isocalendar()[1]
    current_province = get_province_for_week(current_week)
    schedule = get_rotation_schedule()
    total_cities = sum(row["city_count"] for row in schedule)

    print("\n── Province Rotation Schedule ──")
    print(f"Current week: {current_week} → {current_province}\n")
    print(f"{'Slot':<6} {'Province':<26} {'Cities':<8} {'Est. time':<10}")
    print("─" * 54)

    for row in schedule:
        marker = "  ◄ THIS WEEK" if row["province"] == current_province else ""
        time_label = f"~{row['estimated_minutes']} min"
        print(
            f"{row['rotation_slot']:<6} "
            f"{row['province']:<26} "
            f"{row['city_count']:<8} "
            f"{time_label:<10}{marker}"
        )

    print(
        f"\nFull cycle: {len(PROVINCE_ROTATION)} weeks "
        f"({len(PROVINCE_ROTATION)} provinces, {total_cities} cities total)\n"
    )


if __name__ == "__main__":
    print_schedule()
