"""Download daily weather for five MP cities into data/*.csv using only the stdlib.

Existing CSVs are skipped, so a rerun only retries what failed.
Usage: python fetch_data.py [--force]
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
API_URL = "https://archive-api.open-meteo.com/v1/archive"

CITIES = {
    "Indore": (22.72, 75.86),
    "Bhopal": (23.26, 77.41),
    "Gwalior": (26.22, 78.18),
    "Jabalpur": (23.18, 79.99),
    "Ujjain": (23.18, 75.78),
}


def _download(query: str, attempts: int = 4) -> dict:
    """GET the API with retry/backoff; a 429 must not kill the whole run."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(f"{API_URL}?{query}", timeout=120) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                wait = 15 * attempt
                print(f"  attempt {attempt} failed ({exc}); retrying in {wait}s")
                time.sleep(wait)
    raise RuntimeError(f"download failed after {attempts} attempts: {last_error}")


def fetch_city(name: str, lat: float, lon: float, start: str = "1991-01-01",
               end: str | None = None) -> list[tuple[str, str, str]]:
    if end is None:
        end = (date.today() - timedelta(days=7)).isoformat()

    query = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "daily": "temperature_2m_max,precipitation_sum",
        "timezone": "auto",
    })
    payload = _download(query)

    daily = payload.get("daily")
    if not daily:
        raise ValueError(f"{name}: response has no 'daily' block")
    for key in ("time", "temperature_2m_max", "precipitation_sum"):
        if key not in daily:
            raise ValueError(f"{name}: response is missing {key!r}")
        if len(daily[key]) != len(daily["time"]):
            raise ValueError(f"{name}: column {key!r} has an unexpected length")

    rows: list[tuple[str, str, str]] = []
    for day, tmax, rain in zip(daily["time"], daily["temperature_2m_max"],
                               daily["precipitation_sum"]):
        rain_text = "" if rain is None or rain < 0 else str(float(rain))
        rows.append((day, "" if tmax is None else str(float(tmax)), rain_text))

    if not rows:
        raise ValueError(f"{name}: API returned no rows")
    return rows


def save_city(name: str, rows: list[tuple[str, str, str]]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{name.lower()}_daily.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["city", "date", "tmax_c", "rain_mm"])
        for day, tmax, rain in rows:
            writer.writerow([name, day, tmax, rain])
    return path


def main() -> None:
    force = "--force" in sys.argv
    failures = []
    attempted = 0

    for name, (lat, lon) in CITIES.items():
        path = DATA_DIR / f"{name.lower()}_daily.csv"
        if path.exists() and not force:
            print(f"{name}: already saved ({path.stat().st_size:,} bytes), skipping")
            continue
        try:
            if attempted:
                time.sleep(8)  # stay under the free API rate limit
            attempted += 1
            rows = fetch_city(name, lat, lon)
            save_city(name, rows)
            missing = sum(1 for r in rows if r[1] == "" or r[2] == "")
            print(f"{name}: {len(rows):,} rows -> {path.name}; missing={missing}; "
                  f"{rows[0][0]} to {rows[-1][0]}")
        except Exception as exc:
            failures.append(name)
            print(f"ERROR {name}: {exc}")

    if failures:
        print("\nFailed: " + ", ".join(failures))
        print("Keep the CSVs that worked, wait a few minutes, rerun the same command.")
        sys.exit(1)
    print("\nAll five cities saved. The dashboard only needs these CSVs.")


if __name__ == "__main__":
    main()
