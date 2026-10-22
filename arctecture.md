# OMNISIGHT - Minimal Build Blueprint

### STEAM Innovation League 2.0 · Regional Round · 29 October 2026

> **This edition uses a pygame window instead of Streamlit or a local web page.**
> One package to install, one window to show, no server and no browser. The whole
> thing was built and run here - **Python 3.14.6, pygame 2.6.1, aarch64
> Android/Termux** - and every number below is a real measurement. The same code
> runs unchanged on Windows, macOS and Linux.

Guide purpose: build a working, testable, software-only prototype that compares
weather-related water-stress indicators for five cities in Madhya Pradesh.

Project definition: OMNISIGHT is a weather-based water-stress risk indicator. It
is not a drought prediction system, an official warning, or proof of actual water
scarcity.

Source basis: this blueprint follows the uploaded `OMNISIGHT_vs_AQUASENTINEL_Guide`
PDF - Open-Meteo historical daily rainfall and maximum temperature; cities Indore,
Bhopal, Gwalior, Jabalpur and Ujjain; SPI-3 rainfall anomaly, 30-day heat anomaly,
a 60-day dry-spell indicator; an explainable 0-100 score; a what-if simulator; data
caching; validation; and an honest limitations statement.

Source caveats kept from the original: the PDF's sample code was tested on
synthetic data, not against the live API, and its 50/25/25 weights and cut-offs are
design assumptions, not calibrated values. Do not claim real-world accuracy unless
you personally validate it.

---

## 1. The environment - what it is and why

### In one paragraph

OMNISIGHT is now **one Python program that opens its own desktop window**.
`pygame` supplies the window, the drawing calls, the fonts and the mouse/keyboard
events; everything else - the download, the CSV storage, the indicator maths and
the scoring - is the Python standard library. That makes it **one package to
install, on Windows, macOS or Linux**, with prebuilt wheels and no compiler.

| Job | Tool |
| --- | --- |
| Window, pixels, lines, text, input | `pygame` (the only third-party package) |
| Download weather | `urllib.request` |
| Store / read CSVs | `csv` |
| Dates and calendars | `datetime`, `calendar` |
| Percentiles, z-scores, normal distribution | `bisect`, `math`, `statistics.NormalDist` |
| Tests | `unittest` |

### Install and run - the whole story

```bash
python -m pip install -r requirements.txt     # installs pygame, nothing else
python fetch_data.py                          # once, needs internet
python dashboard.py                           # opens the window
```

No virtual environment required, no browser, no local server, no build step, no
admin rights. `requirements.txt` contains exactly one line: `pygame>=2.5`.

### Measured on this device

| Check | Result |
| --- | --- |
| Python | 3.14.6, `aarch64` Android (Termux) |
| pygame | 2.6.1 (SDL 2.32.10) - already installed |
| Third-party imports | 1: `pygame` |
| Data downloaded | 5 CSVs x 13,072 rows, 1991-01-01 to 2026-10-15, 0 missing values, 1.9 MB |
| Cold start (load data + first frame) | 2.6 s |
| Frame time while dragging a slider | 11.7 ms per frame (about 85 fps) |
| Memory | ~63 MB peak |
| Test suite | 26 tests, about 2 s, all pass |
| Window | 1200 x 820 logical pixels, scales to any window size |

### What was removed, and what replaced it

| Old blueprint | Now | Why |
| --- | --- | --- |
| Streamlit UI + web server | one pygame window | No server to start, no browser tab, no port conflicts |
| pandas | `csv` + a tiny `Row` class | Only needed group-by-month and summing |
| NumPy | plain loops and prefix sums | 13k rows x 5 cities takes milliseconds |
| SciPy `gamma.fit` / `gamma.cdf` | ranking against the 1991-2020 baseline + `NormalDist.inv_cdf` | One less compiled dependency; non-parametric SPI |
| Plotly / Folium | `pygame.draw.aalines` and rectangles | No assets, no tiles, no HTML |
| pytest | `unittest` | Built in |
| `requests` | `urllib.request` | Built in |
| venv + many packages | `pip install pygame` | One wheel, three platforms |

### Why this version travels well

* **One dependency, prebuilt wheels** for Windows, macOS and Linux (Intel and
  Apple Silicon). `pip install pygame` does not compile anything.
* **No services**: no port, no localhost, no browser version, no CDN, no tiles.
* **Plain CSV data**: the same files open in Excel, LibreOffice or Google Sheets,
  which is useful when a judge asks to see the raw numbers.
* **Headless-friendly for testing**: the 26 tests run without a display when
  `SDL_VIDEODRIVER=dummy` is set, which is how they are verified here.

### What you give up (say this honestly)

- **A graphical desktop is required for the dashboard.** On this Android/Termux
  device pygame runs, but showing a window needs an X server (termux-x11). The
  download, the indicators and the tests all run headless. Present on a laptop.
- **Fixed canvas, scaled.** The layout is designed for 1200x820 and scales as one
  piece; it does not reflow like a web page. That is the price of no HTML.
- **SPI is empirical, not gamma-fitted.** The latest three-month total is ranked
  against 1991-2020 totals for the same ending month. Values are therefore
  discrete, and the baseline SD is about 0.90 rather than exactly 1.00.
- **No map and no PDF.** The comparison table, the score scale and the two charts
  carry the demo; the screenshot flag produces a PNG for the report.

None of that weakens the science. It removes install risk and server risk, which
is what actually kills demos.

## 2. Create the project

You are already in the `omnisight` folder. Create only what is missing:

```bash
mkdir -p data tests
python -m pip install -r requirements.txt
```

Final structure - five code files, two test files, one dependency:

```text
omnisight/
├── fetch_data.py            # download -> data/*.csv
├── indicators.py            # SPI-3, heat anomaly, dry spell
├── risk_engine.py           # score, level, scenarios, history
├── dashboard.py             # the pygame window
├── requirements.txt         # pygame>=2.5  (the only line)
├── README.md
├── data/                    # created by fetch_data.py (1.9 MB)
│   ├── indore_daily.csv
│   ├── bhopal_daily.csv
│   ├── gwalior_daily.csv
│   ├── jabalpur_daily.csv
│   └── ujjain_daily.csv
└── tests/
    ├── test_indicators.py   # 19 maths tests, no pygame needed
    └── test_dashboard.py    # 7 UI tests, skipped if pygame or data is missing
```

`requirements.txt` is one line:

```text
pygame>=2.5
```

A virtual environment is optional. If you want one:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

## 3. `fetch_data.py` - download and cache

Purpose: request daily maximum temperature and rainfall for the five cities and
write one CSV per city. Handles the two failure modes that actually happened here:
HTTP 429 rate limiting, and rerunning after a partial failure.

```python
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
```

### Run it

```bash
python fetch_data.py
```

Verified output on this device:

```text
Indore: 13,072 rows -> indore_daily.csv; missing=0; 1991-01-01 to 2026-10-15
Bhopal: 13,072 rows -> bhopal_daily.csv; missing=0; 1991-01-01 to 2026-10-15
Gwalior: 13,072 rows -> gwalior_daily.csv; missing=0; 1991-01-01 to 2026-10-15
Jabalpur: 13,072 rows -> jabalpur_daily.csv; missing=0; 1991-01-01 to 2026-10-15
Ujjain: 13,072 rows -> ujjain_daily.csv; missing=0; 1991-01-01 to 2026-10-15

All five cities saved. The dashboard only needs these CSVs.
```

Notes from the real run:

* Open-Meteo returned **HTTP 429** twice during the first attempts. The retry loop
  (15 s, then 30 s, then 45 s) recovered it. This is normal for the free tier.
* Existing CSVs are skipped, so a rerun only retries the city that failed. That
  matters if you are on a slow connection at the venue.
* `--force` re-downloads everything.

Do not type weather numbers by hand to make the project look complete. If you ever
use a demonstration dataset, label it **SIMULATED** on screen.

---

## 4. `indicators.py` - the three indicators

Purpose: turn the raw daily rows into SPI-3, a heat z-score and a dry-spell length.
All explicit about complete months and missing data.

```python
"""Water-stress indicators, implemented with the Python standard library only."""
from __future__ import annotations

import bisect
import calendar
import csv
import math
from datetime import date
from pathlib import Path
from statistics import NormalDist

BASE_START = 1991
BASE_END = 2020
_NORMAL = NormalDist()


class Row:
    """One daily observation. None means the value was missing."""
    __slots__ = ("day", "tmax", "rain")

    def __init__(self, day: date, tmax: float | None, rain: float | None):
        self.day = day
        self.tmax = tmax
        self.rain = rain


def _to_float(text: str) -> float | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_csv(path: Path) -> list[Row]:
    """Read city CSV, sort by date, drop duplicate dates, reject negative rain."""
    if not path.exists():
        raise FileNotFoundError(f"{path.name} not found. Run `python fetch_data.py` first.")
    rows: dict[date, Row] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            try:
                day = date.fromisoformat((raw.get("date") or "").strip())
            except ValueError:
                continue
            tmax = _to_float(raw.get("tmax_c"))
            rain = _to_float(raw.get("rain_mm"))
            if rain is not None and rain < 0:
                raise ValueError(f"{path.name}: negative rainfall on {day}")
            rows[day] = Row(day, tmax, rain)
    if not rows:
        raise ValueError(f"{path.name}: no usable dates")
    return [rows[day] for day in sorted(rows)]


def monthly_totals(rows: list[Row]) -> dict[tuple[int, int], float]:
    """Total rainfall per month, but only for months where every day is present."""
    sums: dict[tuple[int, int], float] = {}
    counts: dict[tuple[int, int], int] = {}
    for row in rows:
        if row.rain is None:
            continue
        key = (row.day.year, row.day.month)
        sums[key] = sums.get(key, 0.0) + row.rain
        counts[key] = counts.get(key, 0) + 1

    complete = {}
    for key, total in sums.items():
        days_in_month = calendar.monthrange(key[0], key[1])[1]
        if counts[key] == days_in_month:
            complete[key] = total
    return complete


def previous_months(year: int, month: int, count: int) -> list[tuple[int, int]]:
    """The `count` months ending at (year, month), oldest first."""
    keys = []
    for offset in range(count - 1, -1, -1):
        index = (year * 12 + (month - 1)) - offset
        keys.append((index // 12, index % 12 + 1))
    return keys


def three_month_totals(rows: list[Row]) -> dict[tuple[int, int], float]:
    """Rainfall over the three months ending in the key month."""
    monthly = monthly_totals(rows)
    totals = {}
    for key in monthly:
        window = previous_months(key[0], key[1], 3)
        if all(month in monthly for month in window):
            totals[key] = sum(monthly[month] for month in window)
    return totals


def fit_spi_baseline(rows: list[Row]) -> dict[int, list[float]]:
    """
    Sorted baseline 3-month totals per ending month, 1991-2020.

    SPI here is empirical (percentile based), not a gamma fit: no SciPy needed
    and no assumption about the rainfall distribution shape.
    """
    totals = three_month_totals(rows)
    baseline: dict[int, list[float]] = {}
    for (year, month), value in totals.items():
        if BASE_START <= year <= BASE_END:
            baseline.setdefault(month, []).append(value)
    for values in baseline.values():
        values.sort()
    return {month: values for month, values in baseline.items() if len(values) >= 10}


def spi_from_total(total: float, month: int, baseline: dict[int, list[float]]) -> float:
    """Map a 3-month total to a standard-normal score using baseline ranks."""
    values = baseline.get(month)
    if not values:
        raise ValueError(f"No SPI baseline for ending month {month}")

    below = bisect.bisect_left(values, total)
    equal = bisect.bisect_right(values, total) - below
    position = below + 0.5 * equal          # mid-rank for ties
    probability = (position + 0.5) / (len(values) + 1.0)
    probability = min(max(probability, 1e-4), 1 - 1e-4)
    return _NORMAL.inv_cdf(probability)


def spi_series(rows: list[Row], baseline: dict[int, list[float]]) -> dict[tuple[int, int], float]:
    output = {}
    for key, total in three_month_totals(rows).items():
        if key[1] in baseline:
            output[key] = spi_from_total(total, key[1], baseline)
    return output


def _rolling_mean(values: list[float | None], window: int) -> list[float | None]:
    """Trailing mean over `window` days; None where the window is incomplete."""
    size = len(values)
    prefix = [0.0] * (size + 1)
    missing = [0] * (size + 1)
    for index, value in enumerate(values):
        prefix[index + 1] = prefix[index] + (value or 0.0)
        missing[index + 1] = missing[index] + (1 if value is None else 0)

    result: list[float | None] = [None] * size
    for index in range(window - 1, size):
        start = index + 1 - window
        if missing[index + 1] - missing[start] == 0:
            result[index] = (prefix[index + 1] - prefix[start]) / window
    return result


def heat_baseline(rows: list[Row], window: int = 30) -> dict[tuple[int, int], tuple[float, float, int]]:
    """Per calendar day (month, day): baseline mean, stdev and sample count."""
    means = _rolling_mean([row.tmax for row in rows], window)
    stats: dict[tuple[int, int], list[float]] = {}
    for row, mean in zip(rows, means):
        if mean is None or not (BASE_START <= row.day.year <= BASE_END):
            continue
        bucket = stats.setdefault((row.day.month, row.day.day), [])
        bucket.append(mean)

    output = {}
    for key, values in stats.items():
        if len(values) < 5:
            continue
        average = sum(values) / len(values)
        variance = sum((value - average) ** 2 for value in values) / (len(values) - 1)
        if variance <= 0:
            continue
        output[key] = (average, math.sqrt(variance), len(values))
    return output


def heat_series(rows: list[Row],
                baseline: dict[tuple[int, int], tuple[float, float, int]] | None = None,
                window: int = 30) -> dict[date, float]:
    """Z-score of the trailing 30-day mean maximum temperature."""
    baseline = baseline or heat_baseline(rows, window)
    means = _rolling_mean([row.tmax for row in rows], window)
    output: dict[date, float] = {}
    for row, mean in zip(rows, means):
        if mean is None:
            continue
        entry = baseline.get((row.day.month, row.day.day))
        if entry is None:
            continue
        output[row.day] = (mean - entry[0]) / entry[1]
    return output


def dry_run_days(rows: list[Row], days: int = 60, threshold_mm: float = 1.0) -> int:
    """Longest run of days below `threshold_mm` inside the last `days` values."""
    recent = [row.rain for row in rows if row.rain is not None][-days:]
    best = current = 0
    for value in recent:
        if value < threshold_mm:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best
```

### What to understand

* **SPI-3**: sum the rainfall of the last three complete months, then rank that
  total against the same three-month total in every year 1991-2020 that ends in
  the same calendar month. The rank becomes a probability, and
  `NormalDist().inv_cdf` turns it into a standard-normal score. SPI `-1` means the
  period is roughly one standard deviation drier than normal; `+1` is wetter.
* **Heat z**: average the last 30 daily maxima, then compare that average with the
  mean of the same calendar day across 1991-2020, divided by that day's standard
  deviation. `+2` means about two standard deviations hotter than usual.
* **Dry spell**: count the longest run of days under 1 mm inside the last 60 days.
* A month counts only if every calendar day is present. That is why the score is
  dated to a **month end**, never to a half-finished month.
* None of these three measure groundwater, reservoirs, demand or household access.

Two implementation details worth defending in questions:

1. `heat_baseline` skips calendar days whose baseline has fewer than five samples
   or zero variance, so a z-score is never produced by dividing by zero.
2. `spi_from_total` clamps the probability to `[1e-4, 1-1e-4]`, so no score can
   ever be `+/-inf`.

---

## 5. `risk_engine.py` - the score

Purpose: combine the indicators into the 0-100 score, assign a level, and apply the
hypothetical what-if changes.

```python
"""Score the five cities from weather indicators. Standard library only."""
from __future__ import annotations

import calendar
from bisect import bisect_left, bisect_right
from datetime import date, timedelta

import indicators as ind

WEIGHTS = {"rain": 0.50, "heat": 0.25, "dry": 0.25}
LEVELS = ((25.0, "Low"), (50.0, "Moderate"), (75.0, "High"), (101.0, "Very high"))


def level_for(score: float) -> str:
    for upper, label in LEVELS:
        if score < upper:
            return label
    return "Very high"


def last_complete_month_end(rows: list[ind.Row]) -> date:
    """Last month-end covered fully by the data; never a partial month."""
    last = rows[-1].day
    month_end = date(last.year, last.month, calendar.monthrange(last.year, last.month)[1])
    if last < month_end:
        month_end = last.replace(day=1) - timedelta(days=1)
    return month_end


def _window(rows: list[ind.Row], start: date, end: date) -> list[ind.Row]:
    """Slice by date without scanning the whole 13k-row history."""
    return rows[bisect_left(rows, start, key=lambda row: row.day):
                bisect_right(rows, end, key=lambda row: row.day)]


def _require_complete(window: list[ind.Row], start: date, end: date, label: str) -> None:
    expected = (end - start).days + 1
    if len(window) != expected:
        raise ValueError(f"{label}: expected {expected} days, found {len(window)}. "
                         "The CSV has a gap; rerun fetch_data.py.")
    if any(row.rain is None or row.tmax is None for row in window):
        raise ValueError(f"{label}: missing weather values; rerun fetch_data.py.")


def assess(rows: list[ind.Row], rain_factor: float = 1.0, temp_add: float = 0.0,
           weights: dict[str, float] | None = None,
           spi_baseline: dict[int, list[float]] | None = None,
           heat_base: dict[tuple[int, int], tuple[float, float, int]] | None = None) -> dict:
    """
    Score the most recent complete month.

    rain_factor and temp_add are hypothetical changes applied to the latest
    three-month rain window and the latest 30 temperature days. The historical
    baselines are never modified, so a scenario is comparable to real history.
    Only the windows that matter are touched, which keeps redraws instant.
    """
    if not 0.0 <= rain_factor <= 2.0:
        raise ValueError("rain_factor must be between 0 and 2")
    if not -5.0 <= temp_add <= 5.0:
        raise ValueError("temp_add must be between -5 and +5")

    end = last_complete_month_end(rows)
    first_year, first_month = ind.previous_months(end.year, end.month, 3)[0]
    start3 = date(first_year, first_month, 1)
    start30 = end - timedelta(days=29)
    start60 = end - timedelta(days=59)

    window60 = _window(rows, start60, end)
    _require_complete(window60, start60, end, "Latest 60 days")
    window30 = window60[-30:]
    window3 = _window(rows, start3, end)
    _require_complete(window3, start3, end, "Latest 3 months")

    data = rows[:bisect_right(rows, end, key=lambda row: row.day)]
    spi_baseline = spi_baseline if spi_baseline is not None else ind.fit_spi_baseline(data)
    heat_base = heat_base if heat_base is not None else ind.heat_baseline(data)

    three_month_total = sum(row.rain for row in window3) * rain_factor
    spi3 = ind.spi_from_total(three_month_total, end.month, spi_baseline)

    entry = heat_base.get((end.month, end.day))
    if entry is None:
        raise ValueError("Heat anomaly unavailable for the latest month-end")
    mean_tmax = sum(row.tmax for row in window30) / len(window30) + temp_add
    heat_z = (mean_tmax - entry[0]) / entry[1]

    best = current = 0
    for row in window60:
        if row.rain * rain_factor < 1.0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    dry_days = best

    components = {
        "rain": min(max(-spi3 / 2.0, 0.0), 1.0),
        "heat": min(max(heat_z / 2.0, 0.0), 1.0),
        "dry": min(max(dry_days / 30.0, 0.0), 1.0),
    }

    active = weights or WEIGHTS
    if set(active) != {"rain", "heat", "dry"}:
        raise ValueError("Weights must be exactly rain, heat and dry")
    if any(value < 0 for value in active.values()):
        raise ValueError("Weights cannot be negative")
    if abs(sum(active.values()) - 1.0) > 1e-9:
        raise ValueError("Weights must sum to 1.0")

    score = 100.0 * sum(active[key] * components[key] for key in components)
    score = round(min(max(score, 0.0), 100.0), 1)

    return {
        "as_of": end.isoformat(),
        "spi3": spi3,
        "heat_z": heat_z,
        "dry_run_days": dry_days,
        "rain_3m_mm": three_month_total,
        "components": components,
        "weights": dict(active),
        "score": score,
        "level": level_for(score),
        "is_scenario": not (abs(rain_factor - 1.0) < 1e-9 and abs(temp_add) < 1e-9),
        "rain_factor": rain_factor,
        "temp_add_c": temp_add,
    }


def history(rows: list[ind.Row], spi_baseline: dict[int, list[float]] | None = None):
    """Monthly rainfall totals and SPI-3 values, oldest first, for charts."""
    baseline = spi_baseline if spi_baseline is not None else ind.fit_spi_baseline(rows)
    monthly = ind.monthly_totals(rows)
    spi = ind.spi_series(rows, baseline)
    return [{"year": key[0], "month": key[1], "rain_mm": monthly[key], "spi3": spi.get(key)}
            for key in sorted(monthly)]
```

### Important behaviour

* The scoring date is the **last complete month end** in the CSV
  (2026-09-30 in the data downloaded here). A partial month is never scored.
* Windows are found by binary search on the date column, so dragging a slider
  rescoring five cities costs about 11 ms per frame. That is why the UI feels
  instant without a web server.
* If the latest 60 days or the last three months have a gap or a missing value,
  the engine raises a readable error instead of inventing a number.
* Scenario changes touch only the latest 3-month rainfall window and the latest 30
  temperature days. **Historical baselines are never modified**, so a scenario is
  a fair comparison against real history, not a new climate.
* Weights are validated: exactly `rain`, `heat`, `dry`, non-negative, summing to 1.

Verified scores on the data downloaded here (real mode, `as_of` 2026-09-30):

| City | Score | Level | SPI-3 | Heat z | Dry days | Rain 3m (mm) |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| Indore | 31.4 | Moderate | -0.60 | +0.58 | 11 | 630 |
| Ujjain | 16.8 | Low | -0.25 | +0.12 | 11 | 674 |
| Bhopal | 16.0 | Low | -0.51 | -0.37 | 4 | 732 |
| Gwalior | 5.0 | Low | +0.25 | -0.69 | 6 | 713 |
| Jabalpur | 3.3 | Low | +0.70 | -0.33 | 4 | 1,096 |

With the scenario rainfall x0.70 and temperature +2 °C, the same cities score
Bhopal 65.9, Indore 64.4, Ujjain 60.4, Jabalpur 38.6, Gwalior 22.9 - a good
demonstration that the model responds to the sliders, and that heat and dry-spell
components do not move as much as rainfall.

## 6. Tests - verification without internet

Two suites: the maths (no pygame required) and the window interactions (skipped
automatically if pygame or the CSVs are absent, so a bare machine can still run
the suite).

### `tests/test_indicators.py`

```python
"""Calculation tests. Run with: python -m unittest discover -s tests -v"""
from __future__ import annotations

import calendar
import math
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import indicators as ind
from risk_engine import level_for


def make_rows(start: date, days: int, rain: float = 1.0, tmax: float = 30.0):
    return [ind.Row(start + timedelta(days=i), tmax, rain) for i in range(days)]


class MonthlyTotals(unittest.TestCase):
    def test_complete_month_is_summed(self):
        rows = make_rows(date(2020, 1, 1), 31, rain=1.0)
        self.assertEqual(ind.monthly_totals(rows)[(2020, 1)], 31.0)

    def test_incomplete_month_is_dropped(self):
        rows = make_rows(date(2020, 1, 1), 30, rain=1.0)  # January needs 31
        self.assertNotIn((2020, 1), ind.monthly_totals(rows))

    def test_month_with_missing_values_is_dropped(self):
        rows = make_rows(date(2020, 2, 1), 29)
        rows[5].rain = None
        self.assertNotIn((2020, 2), ind.monthly_totals(rows))


class ThreeMonthWindow(unittest.TestCase):
    def test_needs_three_complete_months(self):
        rows = make_rows(date(2020, 1, 1), 31 + 29 + 31, rain=1.0)
        totals = ind.three_month_totals(rows)
        self.assertNotIn((2020, 2), totals)
        self.assertEqual(totals[(2020, 3)], 31 + 29 + 31)

    def test_previous_months_crosses_year_boundary(self):
        self.assertEqual(ind.previous_months(2021, 1, 3),
                         [(2020, 11), (2020, 12), (2021, 1)])


class Spi(unittest.TestCase):
    def setUp(self):
        # 20 baseline totals per month, evenly spaced 100..2000 mm.
        self.baseline = {9: [100.0 * i for i in range(1, 21)]}

    def test_median_gives_zero(self):
        self.assertAlmostEqual(ind.spi_from_total(1050.0, 9, self.baseline), 0.0, places=1)

    def test_dry_is_negative_and_wet_is_positive(self):
        self.assertLess(ind.spi_from_total(150.0, 9, self.baseline), -1.0)
        self.assertGreater(ind.spi_from_total(1950.0, 9, self.baseline), 1.0)

    def test_never_infinite(self):
        for total in (0.0, 0.5, 10_000.0):
            value = ind.spi_from_total(total, 9, self.baseline)
            self.assertTrue(abs(value) < 10, value)

    def test_missing_month_raises(self):
        with self.assertRaises(ValueError):
            ind.spi_from_total(500.0, 4, self.baseline)


class DrySpell(unittest.TestCase):
    def test_longest_run(self):
        amounts = [0, 0, 2, 0, 0, 0, 3, 0, 0, 0]
        rows = [ind.Row(date(2024, 1, 1) + timedelta(days=i), 30, a)
                for i, a in enumerate(amounts)]
        self.assertEqual(ind.dry_run_days(rows, days=10), 3)

    def test_only_last_window_counts(self):
        amounts = [0] * 10 + [1.0] * 5 + [0, 0]
        rows = [ind.Row(date(2024, 1, 1) + timedelta(days=i), 30, a)
                for i, a in enumerate(amounts)]
        self.assertEqual(ind.dry_run_days(rows, days=7), 2)


class Heat(unittest.TestCase):
    def test_zscore_math(self):
        rows = make_rows(date(2024, 6, 1), 40, tmax=34.0)
        base = {(6, day): (30.0, 2.0, 30) for day in range(1, 31)}
        series = ind.heat_series(rows, base)
        # 30-day mean 34 vs baseline mean 30, sd 2 -> z = 2
        self.assertAlmostEqual(series[date(2024, 6, 30)], 2.0, places=6)

    def test_baseline_skips_constant_history(self):
        # Zero variance would divide by zero, so those calendar days are skipped.
        rows = make_rows(date(1991, 1, 1), 400, tmax=30.0)
        self.assertEqual(ind.heat_baseline(rows), {})

    def test_baseline_keeps_varying_history(self):
        rows = [ind.Row(date(1991, 1, 1) + timedelta(days=i), 30.0 + ((i * 37) % 11) * 0.5, 0.0)
                for i in range(2260)]  # ~6 baseline years
        base = ind.heat_baseline(rows)
        self.assertTrue(base)
        mean, sd, count = base[(6, 1)]
        self.assertGreater(sd, 0)
        self.assertGreater(count, 5)


class Levels(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(level_for(0), "Low")
        self.assertEqual(level_for(24.9), "Low")
        self.assertEqual(level_for(25), "Moderate")
        self.assertEqual(level_for(50), "High")
        self.assertEqual(level_for(75), "Very high")
        self.assertEqual(level_for(100), "Very high")


class Scenarios(unittest.TestCase):
    """The what-if maths must be identical to the real-data maths at 1.0/0.0."""

    @classmethod
    def setUpClass(cls):
        rows = []
        for year in range(1991, 2023):
            for month in range(1, 13):
                for day in range(1, calendar.monthrange(year, month)[1] + 1):
                    rain = (8.0 if month in (7, 8, 9) else 0.4) + (year % 5)
                    tmax = (30 + 5 * math.sin((month - 1) / 12 * 2 * math.pi)
                            + ((year * 31 + day * 17) % 7) * 0.15)
                    rows.append(ind.Row(date(year, month, day), tmax, rain))
        import risk_engine as engine
        cls.engine = engine
        cls.rows = rows
        cls.spi = ind.fit_spi_baseline(rows)
        cls.heat = ind.heat_baseline(rows)
        cls.base = engine.assess(rows, spi_baseline=cls.spi, heat_base=cls.heat)

    def check(self, **kwargs):
        return self.engine.assess(self.rows, spi_baseline=self.spi, heat_base=self.heat, **kwargs)

    def test_neutral_scenario_equals_real_data(self):
        neutral = self.check(rain_factor=1.0, temp_add=0.0)
        for key in ("score", "spi3", "heat_z", "dry_run_days", "rain_3m_mm"):
            self.assertEqual(neutral[key], self.base[key])
        self.assertFalse(neutral["is_scenario"])

    def test_rain_factor_scales_the_window_total(self):
        wet = self.check(rain_factor=1.5)
        self.assertAlmostEqual(wet["rain_3m_mm"], self.base["rain_3m_mm"] * 1.5, places=6)
        self.assertGreater(wet["spi3"], self.base["spi3"])
        self.assertLessEqual(wet["score"], self.base["score"])

    def test_temperature_change_shifts_the_z_score(self):
        sd = self.heat[(12, 31)][1]
        hotter = self.check(temp_add=2.0)
        self.assertAlmostEqual(hotter["heat_z"] - self.base["heat_z"], 2.0 / sd, places=6)

    def test_dry_spell_is_unchanged_by_a_multiplier(self):
        drier = self.check(rain_factor=0.7)
        self.assertEqual(drier["dry_run_days"], self.base["dry_run_days"])


if __name__ == "__main__":
    unittest.main()
```

### `tests/test_dashboard.py`

```python
"""Dashboard interaction tests.

Skipped automatically when pygame is missing or the CSVs are not downloaded,
so `python -m unittest` still works on a bare machine.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before pygame initialises; harmless on desktops with a display.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

try:
    import pygame
except ImportError:  # pragma: no cover - depends on the machine
    pygame = None


@unittest.skipIf(pygame is None, "pygame is not installed")
class DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import dashboard
        cls.module = dashboard
        pygame.init()
        cls.screen = pygame.display.set_mode((dashboard.WIDTH, dashboard.HEIGHT))
        try:
            cities, meta = dashboard.load_cities()
        except FileNotFoundError as exc:
            pygame.quit()
            raise unittest.SkipTest(f"city data missing: {exc}")
        cls.board = dashboard.Dashboard(cities, meta)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        self.board.rain = 1.0
        self.board.temp = 0.0
        self.board.drag = None
        self.board.active = "rain"
        self.board.selected = self.board.order()[0]

    def key(self, code: int) -> bool:
        return self.board.handle(pygame.event.Event(pygame.KEYDOWN, key=code, mod=0, unicode=""))

    def click(self, pos) -> None:
        self.board.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
        self.board.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1))

    def test_number_keys_select_the_visible_row(self):
        self.key(pygame.K_3)
        self.assertEqual(self.board.selected, self.board.order()[2])

    def test_arrows_respect_limits_and_tab_switches(self):
        self.key(pygame.K_TAB)
        self.assertEqual(self.board.active, "temp")
        for _ in range(20):
            self.key(pygame.K_RIGHT)
        self.assertEqual(self.board.temp, 5.0)
        for _ in range(30):
            self.key(pygame.K_LEFT)
        self.assertEqual(self.board.temp, -2.0)

    def test_dragging_slider_sets_value(self):
        track = self.board.rain_track
        self.board.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                            pos=(track.left, track.centery), button=1))
        self.assertEqual(self.board.rain, 0.0)
        self.assertEqual(self.board.drag, "rain")
        self.board.handle(pygame.event.Event(pygame.MOUSEMOTION,
                                            pos=(track.right, track.centery),
                                            rel=(0, 0), buttons=(1, 0, 0)))
        self.assertEqual(self.board.rain, 1.5)
        self.board.handle(pygame.event.Event(pygame.MOUSEBUTTONUP,
                                            pos=(track.right, track.centery), button=1))
        self.assertIsNone(self.board.drag)

    def test_clicking_a_row_selects_that_city(self):
        expected = self.board.order()[2]
        self.click(self.board.city_rows[2].center)
        self.assertEqual(self.board.selected, expected)

    def test_reset_returns_to_real_data(self):
        self.board.rain, self.board.temp = 0.3, 3.0
        self.key(pygame.K_r)
        self.assertEqual((self.board.rain, self.board.temp), (1.0, 0.0))
        self.assertFalse(self.board.score(self.board.selected)["is_scenario"])

    def test_escape_closes_the_window(self):
        self.assertFalse(self.key(pygame.K_ESCAPE))

    def test_frames_render_for_every_city(self):
        for city in self.board.cities:
            self.board.selected = city
            self.board.draw(self.screen)
        self.assertEqual(self.screen.get_size(), (self.module.WIDTH, self.module.HEIGHT))


if __name__ == "__main__":
    unittest.main()
```

### Run

```bash
python -m unittest discover -s tests -v
```

Verified output:

```text
Ran 26 tests in 2.08s

OK
```

The maths tests cover: complete vs incomplete months, a month with one missing
value, the three-month window crossing a year boundary, SPI median/dry/wet
behaviour, finite SPI at the extremes, the dry-spell scan and its 60-day window,
the heat z-score arithmetic, the zero-variance guard, the risk level boundaries,
and the four scenario invariants (neutral 1.0/0.0 is identical to real data, the
rain multiplier scales the window total, a temperature change shifts the z-score
by exactly delta/SD, and a multiplier leaves the dry spell alone).

The UI tests cover: number keys select a city, Tab plus arrows adjust a slider
within its limits, dragging a slider sets the value, clicking a row selects the
matching city, reset returns to real data, Esc closes, and every city renders a
frame without error.

If any test fails, fix the code before presenting.

## 7. `dashboard.py` - the pygame window

Purpose: one window that shows the five-city comparison, the selected city's
indicators and charts, the score breakdown, and the what-if sliders. No HTML, no
server, no assets - everything is drawn from rectangles, lines and text.

```python
"""
OMNISIGHT - weather-based water-stress dashboard.

Plain pygame: one window, no web server, no browser, no assets. Runs on
Windows, macOS and Linux with `python -m pip install pygame`.

    python fetch_data.py
    python dashboard.py

Keys: 1-5 city, Tab switch slider, arrows adjust, R reset, E save CSV, Esc quit.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

try:
    import pygame
except ImportError:  # a friendlier message than a traceback
    raise SystemExit("pygame is not installed.\nRun:  python -m pip install pygame")

import indicators as ind
import risk_engine as eng
from fetch_data import CITIES, DATA_DIR

WIDTH, HEIGHT = 1200, 820

INK = (15, 23, 42)
MUTED = (100, 116, 139)
LINE = (226, 232, 240)
BG = (246, 248, 251)
CARD = (255, 255, 255)
ACCENT = (37, 99, 235)
ACCENT_SOFT = (239, 246, 255)
WARN_BG = (255, 247, 237)
WARN_INK = (154, 52, 18)
GRID = (241, 245, 249)
LEVEL_COLOR = {"Low": (21, 128, 61), "Moderate": (180, 83, 9),
               "High": (194, 65, 12), "Very high": (185, 28, 28)}

_FONTS: dict[tuple[int, bool], "pygame.font.Font"] = {}


def font(size: int, bold: bool = False) -> "pygame.font.Font":
    key = (size, bold)
    if key not in _FONTS:
        path = pygame.font.match_font("dejavusans,liberationsans,arial,helvetica,freesans",
                                      bold=bold)
        _FONTS[key] = pygame.font.Font(path, size) if path else pygame.font.Font(None, size)
    return _FONTS[key]


_TEXT_CACHE: dict[tuple, "pygame.Surface"] = {}


def text(surface, value: str, xy, size: int = 14, color=INK, bold: bool = False,
         anchor: str = "topleft"):
    key = (str(value), size, color, bold)
    image = _TEXT_CACHE.get(key)
    if image is None:
        if len(_TEXT_CACHE) > 600:
            _TEXT_CACHE.clear()
        image = _TEXT_CACHE[key] = font(size, bold).render(key[0], True, color)
    rect = image.get_rect(**{anchor: xy})
    surface.blit(image, rect)
    return rect


def panel(surface, rect, fill=CARD, border=LINE, radius=12) -> None:
    pygame.draw.rect(surface, fill, rect, border_radius=radius)
    pygame.draw.rect(surface, border, rect, width=1, border_radius=radius)


def chip(surface, rect, label: str, bg, fg, size: int = 13) -> None:
    pygame.draw.rect(surface, bg, rect, border_radius=999)
    text(surface, label, rect.center, size, fg, bold=True, anchor="center")


def line_chart(surface, rect, values, color, title: str, unit: str,
               zero_line: bool = False, years: tuple[int, int] | None = None) -> None:
    """Small, dependency-free line chart with three gridlines and axis labels."""
    panel(surface, rect)
    text(surface, title, (rect.x + 14, rect.y + 12), 13, INK, bold=True)

    plot = pygame.Rect(rect.x + 46, rect.y + 40, rect.width - 62, rect.height - 74)
    if len(values) < 2:
        text(surface, "no data", plot.center, 13, MUTED, anchor="center")
        return

    low, high = min(values), max(values)
    if zero_line:
        low, high = min(low, 0.0), max(high, 0.0)
    if high - low < 1e-9:
        high = low + 1.0
    span = high - low
    decimals = 0 if span >= 10 else 1

    for fraction in (0.0, 0.5, 1.0):
        y = plot.bottom - fraction * plot.height
        pygame.draw.line(surface, GRID, (plot.left, y), (plot.right, y))
        text(surface, f"{low + span * fraction:,.{decimals}f}",
             (plot.left - 8, y), 11, MUTED, anchor="midright")

    if zero_line and low < 0 < high:
        y = plot.bottom - (0 - low) / span * plot.height
        for x in range(plot.left, plot.right, 7):
            pygame.draw.line(surface, (203, 213, 225), (x, y), (x + 4, y))

    step = plot.width / (len(values) - 1)
    points = [(plot.left + i * step, plot.bottom - (v - low) / span * plot.height)
              for i, v in enumerate(values)]
    pygame.draw.aalines(surface, color, False, points)

    if years:
        text(surface, str(years[0]), (plot.left, plot.bottom + 8), 11, MUTED)
        text(surface, str(years[1]), (plot.right, plot.bottom + 8), 11, MUTED, anchor="topright")
    text(surface, unit, (rect.right - 14, rect.y + 12), 11, MUTED, anchor="topright")


class Dashboard:
    def __init__(self, cities: dict[str, dict], meta: dict):
        self.cities = cities
        self.meta = meta
        self.selected = next(iter(cities))
        self.rain = 1.0
        self.temp = 0.0
        self.drag: str | None = None
        self.active = "rain"
        self.hover: str | None = None
        self.status = ""
        self.status_until = 0
        self.by_city: dict[str, dict] = {}

        # layout: left column of cards, right column of detail
        self.left = pygame.Rect(28, 104, 356, HEIGHT - 104 - 56)
        self.cities_panel = pygame.Rect(self.left.x, self.left.y, 356, 300)
        self.scenario_panel = pygame.Rect(self.left.x, 416, 356, 214)
        self.info_panel = pygame.Rect(self.left.x, 642, 356, 118)
        self.right = pygame.Rect(402, 104, WIDTH - 402 - 28, HEIGHT - 104 - 56)
        self.title_panel = pygame.Rect(self.right.x, self.right.y, self.right.width, 58)
        self.tiles_panel = pygame.Rect(self.right.x, 172, self.right.width, 76)
        self.gauge_panel = pygame.Rect(self.right.x, 258, self.right.width, 74)
        self.chart_left = pygame.Rect(self.right.x, 342, 370, 208)
        self.chart_right = pygame.Rect(self.right.x + 384, 342, 370, 208)
        self.breakdown_panel = pygame.Rect(self.right.x, 560, self.right.width, 180)

        self.city_rows = [pygame.Rect(self.cities_panel.x + 12,
                                      self.cities_panel.y + 52 + i * 47,
                                      self.cities_panel.width - 24, 42)
                          for i in range(len(cities))]

        self.rain_track = pygame.Rect(self.scenario_panel.x + 20, self.scenario_panel.y + 74,
                                      self.scenario_panel.width - 40, 6)
        self.temp_track = pygame.Rect(self.scenario_panel.x + 20, self.scenario_panel.y + 142,
                                      self.scenario_panel.width - 40, 6)
        self.reset_btn = pygame.Rect(self.scenario_panel.x + 20,
                                     self.scenario_panel.y + 172, 92, 30)
        self.save_btn = pygame.Rect(self.scenario_panel.x + 122,
                                    self.scenario_panel.y + 172, 104, 30)

    # ---------- data ----------
    def score(self, city: str) -> dict:
        data = self.cities[city]
        return eng.assess(data["rows"], self.rain, self.temp,
                          spi_baseline=data["spi"], heat_base=data["heat"])

    def results(self) -> list[tuple[str, dict]]:
        return sorted(((city, self.score(city)) for city in self.cities),
                      key=lambda item: item[1]["score"], reverse=True)

    def order(self) -> list[str]:
        return [city for city, _ in self.results()]

    def save_csv(self) -> Path:
        target = DATA_DIR / "omnisight_results.csv"
        lines = ["city,score,level,spi3,heat_z,dry_run_days,rain_3m_mm,as_of,"
                 "rain_factor,temp_add_c"]
        for city, r in self.results():
            lines.append(f'{city},{r["score"]},{r["level"]},{r["spi3"]:.3f},'
                         f'{r["heat_z"]:.3f},{r["dry_run_days"]},{r["rain_3m_mm"]:.1f},'
                         f'{r["as_of"]},{self.rain:.2f},{self.temp:.1f}')
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target

    def export(self) -> None:
        try:
            self.status = f"Saved {self.save_csv().name}"
        except OSError as exc:
            self.status = f"Save failed: {exc.strerror or exc}"
        self.status_until = pygame.time.get_ticks() + 2500

    # ---------- interaction ----------
    @staticmethod
    def _value_at(track: pygame.Rect, x: int, low: float, high: float, step: float) -> float:
        ratio = min(max((x - track.left) / track.width, 0.0), 1.0)
        value = low + ratio * (high - low)
        return round(round(value / step) * step, 2)

    def handle(self, event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_q):
                return False
            if pygame.K_1 <= event.key <= pygame.K_5:
                index = event.key - pygame.K_1
                order = self.order()
                if index < len(order):
                    self.selected = order[index]
            elif event.key == pygame.K_TAB:
                self.active = "temp" if self.active == "rain" else "rain"
            elif event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
                direction = -1 if event.key in (pygame.K_LEFT, pygame.K_DOWN) else 1
                if self.active == "rain":
                    self.rain = round(min(max(self.rain + 0.05 * direction, 0.0), 1.5), 2)
                else:
                    self.temp = round(min(max(self.temp + 0.5 * direction, -2.0), 5.0), 1)
            elif event.key == pygame.K_r:
                self.rain, self.temp = 1.0, 0.0
            elif event.key == pygame.K_e:
                self.export()

        if event.type == pygame.MOUSEMOTION:
            pos = event.pos
            self.hover = next((city for city, rect
                               in zip(self.order(), self.city_rows) if rect.collidepoint(pos)),
                              None)
            if self.drag == "rain":
                self.rain = self._value_at(self.rain_track, pos[0], 0.0, 1.5, 0.05)
            elif self.drag == "temp":
                self.temp = self._value_at(self.temp_track, pos[0], -2.0, 5.0, 0.5)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            for city, rect in zip(self.order(), self.city_rows):
                if rect.collidepoint(pos):
                    self.selected = city
            for name, track in (("rain", self.rain_track), ("temp", self.temp_track)):
                knob_x = self._knob_x(track)
                hit = pygame.Rect(track.x - 10, track.y - 16, track.width + 20, 32)
                if hit.collidepoint(pos) or (abs(pos[0] - knob_x) < 12
                                             and abs(pos[1] - track.centery) < 16):
                    self.drag = name
                    self.active = name
                    low, high = (0.0, 1.5) if name == "rain" else (-2.0, 5.0)
                    step = 0.05 if name == "rain" else 0.5
                    value = self._value_at(track, pos[0], low, high, step)
                    setattr(self, name, value)
            if self.reset_btn.collidepoint(pos):
                self.rain, self.temp = 1.0, 0.0
            if self.save_btn.collidepoint(pos):
                self.export()

        if event.type == pygame.MOUSEBUTTONUP:
            self.drag = None
        return True

    def _knob_x(self, track: pygame.Rect) -> int:
        low, high = (0.0, 1.5) if track is self.rain_track else (-2.0, 5.0)
        value = self.rain if track is self.rain_track else self.temp
        return int(track.left + (value - low) / (high - low) * track.width)

    # ---------- drawing ----------
    def draw(self, surface) -> None:
        self.frame = self.results()
        self.by_city = dict(self.frame)
        self.city_order = [city for city, _ in self.frame]
        surface.fill(BG)
        self._header(surface)
        self._city_panel(surface)
        self._scenario_panel(surface)
        self._info_panel(surface)
        self._title(surface)
        self._tiles(surface)
        self._gauge(surface)
        self._charts(surface)
        self._breakdown(surface)
        self._footer(surface)

    def _header(self, surface) -> None:
        text(surface, "OMNISIGHT", (28, 22), 28, INK, bold=True)
        text(surface, "Weather-based water-stress risk indicator  ·  five Madhya Pradesh cities",
             (196, 32), 14, MUTED)

        scenario = abs(self.rain - 1.0) > 1e-9 or abs(self.temp) > 1e-9
        if scenario:
            label = f"SCENARIO  ·  rain x{self.rain:.2f}  ·  {self.temp:+.1f} °C"
            bg, fg = WARN_BG, WARN_INK
        else:
            label = "REAL DATA  ·  saved historical weather"
            bg, fg = ACCENT_SOFT, (30, 58, 138)
        rect = font(13, True).render(label, True, fg).get_rect()
        pill = pygame.Rect(WIDTH - 28 - rect.width - 28, 26, rect.width + 28, 30)
        chip(surface, pill, label, bg, fg)

    def _city_panel(self, surface) -> None:
        panel(surface, self.cities_panel)
        text(surface, "1. City comparison", (self.cities_panel.x + 18, self.cities_panel.y + 18),
             16, INK, bold=True)
        text(surface, "click a city  ·  or press 1-5", (self.cities_panel.right - 18,
                                                       self.cities_panel.y + 22),
             11, MUTED, anchor="topright")

        results = self.by_city
        for city, rect in zip(self.city_order, self.city_rows):
            selected = city == self.selected
            if selected:
                pygame.draw.rect(surface, ACCENT_SOFT, rect, border_radius=8)
                pygame.draw.rect(surface, ACCENT, pygame.Rect(rect.x, rect.y + 8, 3,
                                                              rect.height - 16), border_radius=2)
            elif city == self.hover:
                pygame.draw.rect(surface, (248, 250, 252), rect, border_radius=8)

            result = results[city]
            color = LEVEL_COLOR.get(result["level"], MUTED)
            text(surface, city, (rect.x + 12, rect.centery), 13, INK,
                 bold=selected, anchor="midleft")
            bar = pygame.Rect(rect.x + 92, rect.centery - 5, 150, 10)
            pygame.draw.rect(surface, (238, 242, 247), bar, border_radius=5)
            width = max(int(bar.width * result["score"] / 100.0), 3)
            pygame.draw.rect(surface, color, pygame.Rect(bar.x, bar.y, width, bar.height),
                             border_radius=5)
            text(surface, f'{result["score"]:.1f}', (rect.right - 66, rect.centery), 13, INK,
                 bold=True, anchor="midright")
            chip(surface, pygame.Rect(rect.right - 60, rect.centery - 11, 60, 22),
                 result["level"], (*color, 255), (255, 255, 255), 10)

    def _scenario_panel(self, surface) -> None:
        panel(surface, self.scenario_panel)
        text(surface, "2. What-if scenario", (self.scenario_panel.x + 18,
                                             self.scenario_panel.y + 18), 16, INK, bold=True)
        text(surface, "hypothetical, not a forecast", (self.scenario_panel.right - 18,
                                                       self.scenario_panel.y + 22),
             11, MUTED, anchor="topright")

        for name, track, label, value in (
            ("rain", self.rain_track, "Rainfall, latest 3 months", f"x{self.rain:.2f}"),
            ("temp", self.temp_track, "Temperature, latest 30 days", f"{self.temp:+.1f} °C"),
        ):
            text(surface, label, (track.x, track.y - 26), 12, MUTED)
            text(surface, value, (track.right, track.y - 26), 13,
                 WARN_INK if name == self.active else INK, bold=True, anchor="topright")
            pygame.draw.rect(surface, LINE, track, border_radius=3)
            knob = self._knob_x(track)
            pygame.draw.rect(surface, ACCENT, pygame.Rect(track.left, track.y,
                                                          knob - track.left, track.height),
                             border_radius=3)
            pygame.draw.circle(surface, CARD, (knob, track.centery), 9)
            pygame.draw.circle(surface, ACCENT, (knob, track.centery), 9, 2)

        for rect, label, key in ((self.reset_btn, "Reset  R", "r"),
                                 (self.save_btn, "Save CSV  E", "e")):
            hover = rect.collidepoint(pygame.mouse.get_pos())
            panel(surface, rect, (241, 245, 249) if hover else CARD)
            text(surface, label, rect.center, 12, INK, anchor="center")

        text(surface, "x0.0", (self.rain_track.left, self.rain_track.bottom + 6), 10, MUTED)
        text(surface, "x1.5", (self.rain_track.right, self.rain_track.bottom + 6), 10,
             MUTED, anchor="topright")
        text(surface, "-2 °C", (self.temp_track.left, self.temp_track.bottom + 6), 10, MUTED)
        text(surface, "+5 °C", (self.temp_track.right, self.temp_track.bottom + 6), 10,
             MUTED, anchor="topright")

    def _info_panel(self, surface) -> None:
        panel(surface, self.info_panel)
        text(surface, "Data", (self.info_panel.x + 18, self.info_panel.y + 16), 11,
             MUTED, bold=True)
        text(surface, f"Open-Meteo reanalysis {self.meta['start']}-{self.meta['end']}",
             (self.info_panel.x + 18, self.info_panel.y + 36), 12, INK)
        text(surface, f"{self.meta['days']:,} days per city · stored as CSV",
             (self.info_panel.x + 18, self.info_panel.y + 54), 12, INK)
        text(surface, "Weights 50/25/25 are design assumptions", (self.info_panel.x + 18,
                                                                  self.info_panel.y + 78),
             11, MUTED)
        if self.status and pygame.time.get_ticks() < self.status_until:
            text(surface, self.status, (self.info_panel.right - 18, self.info_panel.y + 16),
                 11, LEVEL_COLOR["Low"], bold=True, anchor="topright")

    def _title(self, surface) -> None:
        result = self.by_city[self.selected]
        color = LEVEL_COLOR.get(result["level"], INK)
        text(surface, self.selected, (self.title_panel.x, self.title_panel.y + 4), 24, INK,
             bold=True)
        text(surface, f'assessed {result["as_of"]}  ·  latest complete month',
             (self.title_panel.x, self.title_panel.y + 34), 12, MUTED)
        badge = pygame.Rect(self.title_panel.right - 196, self.title_panel.y + 6, 196, 42)
        pygame.draw.rect(surface, color, badge, border_radius=10)
        score_rect = text(surface, f'{result["score"]:.1f}',
                          (badge.x + 14, badge.centery), 23, (255, 255, 255),
                          bold=True, anchor="midleft")
        text(surface, "/100", (score_rect.right + 4, badge.centery + 1), 11,
             (255, 255, 255), anchor="midleft")
        text(surface, result["level"], (badge.right - 14, badge.centery), 12,
             (255, 255, 255), bold=True, anchor="midright")

    def _tiles(self, surface) -> None:
        result = self.by_city[self.selected]
        fields = (
            ("SPI-3", f'{result["spi3"]:+.2f}', "rainfall anomaly"),
            ("Heat anomaly", f'{result["heat_z"]:+.2f}', "z-score"),
            ("Dry spell", f'{result["dry_run_days"]} d', "max in 60 days"),
            ("Rain, 3 months", f'{result["rain_3m_mm"]:,.0f} mm', "window total"),
        )
        gap = 12
        width = (self.tiles_panel.width - gap * 3) / 4
        for index, (name, value, note) in enumerate(fields):
            rect = pygame.Rect(self.tiles_panel.x + index * (width + gap), self.tiles_panel.y,
                               width, self.tiles_panel.height)
            panel(surface, rect)
            text(surface, name, (rect.x + 14, rect.y + 12), 11, MUTED, bold=True)
            text(surface, value, (rect.x + 14, rect.y + 30), 21, INK, bold=True)
            text(surface, note, (rect.x + 14, rect.y + 56), 10, MUTED)

    def _gauge(self, surface) -> None:
        result = self.by_city[self.selected]
        panel(surface, self.gauge_panel)
        text(surface, "Score scale", (self.gauge_panel.x + 16, self.gauge_panel.y + 10),
             11, MUTED, bold=True)
        track = pygame.Rect(self.gauge_panel.x + 16, self.gauge_panel.y + 34,
                            self.gauge_panel.width - 32, 12)
        for index, (low, high, name) in enumerate(((0, 25, "Low"), (25, 50, "Moderate"),
                                                   (50, 75, "High"), (75, 100, "Very high"))):
            start = track.left + int(track.width * low / 100)
            end = track.left + int(track.width * high / 100)
            pygame.draw.rect(surface, (*LEVEL_COLOR[name], 255),
                             pygame.Rect(start, track.y, end - start - 2, track.height))
            text(surface, name, (start + 4, track.bottom + 6), 9, MUTED)
        marker = track.left + int(track.width * result["score"] / 100)
        pygame.draw.circle(surface, CARD, (marker, track.centery), 7)
        pygame.draw.circle(surface, INK, (marker, track.centery), 7, 2)
        text(surface, "prototype thresholds", (track.right, self.gauge_panel.y + 10), 10,
             MUTED, anchor="topright")

    def _charts(self, surface) -> None:
        data = self.cities[self.selected]
        history = data["history"]
        recent = history[-180:] if len(history) > 180 else history
        rain = [point["rain_mm"] for point in recent]
        spi = [point["spi3"] for point in recent if point["spi3"] is not None]
        years = (recent[0]["year"], recent[-1]["year"]) if recent else None
        line_chart(surface, self.chart_left, rain, ACCENT, "Monthly rainfall (last 15 years)", "mm",
                   years=years)
        line_chart(surface, self.chart_right, spi, (124, 58, 237), "SPI-3 (last 15 years)",
                   "standard deviations", zero_line=True, years=years)

    def _breakdown(self, surface) -> None:
        result = self.by_city[self.selected]
        panel(surface, self.breakdown_panel)
        text(surface, "3. Why this score?", (self.breakdown_panel.x + 18,
                                             self.breakdown_panel.y + 16), 16, INK, bold=True)
        text(surface, "score = 100 x (0.50 rain + 0.25 heat + 0.25 dry), each part clipped 0-1",
             (self.breakdown_panel.right - 18, self.breakdown_panel.y + 20), 11, MUTED,
             anchor="topright")

        columns = (("Indicator", 0, "left"), ("Raw", 0.52, "right"),
                   ("0-1", 0.62, "right"), ("Weight", 0.72, "right"),
                   ("Points", 0.84, "right"))
        header_y = self.breakdown_panel.y + 50
        for label, fraction, align in columns:
            x = self.breakdown_panel.x + 18 + fraction * (self.breakdown_panel.width - 36)
            text(surface, label, (x, header_y), 10, MUTED, bold=True,
                 anchor="topright" if align == "right" else "topleft")

        rows = (
            ("Rainfall deficit (SPI-3)", f'{result["spi3"]:+.2f}', result["components"]["rain"],
             result["weights"]["rain"]),
            ("Heat anomaly", f'{result["heat_z"]:+.2f}', result["components"]["heat"],
             result["weights"]["heat"]),
            ("Dry spell", f'{result["dry_run_days"]} d', result["components"]["dry"],
             result["weights"]["dry"]),
        )
        for index, (name, raw, part, weight) in enumerate(rows):
            y = header_y + 26 + index * 30
            pygame.draw.line(surface, GRID, (self.breakdown_panel.x + 18, y - 6),
                             (self.breakdown_panel.right - 18, y - 6))
            text(surface, name, (self.breakdown_panel.x + 18, y), 13, INK)
            for value, fraction in ((raw, 0.52), (f"{part:.3f}", 0.62),
                                    (f"{weight:.2f}", 0.72),
                                    (f"{100 * part * weight:.1f}", 0.84)):
                x = self.breakdown_panel.x + 18 + fraction * (self.breakdown_panel.width - 36)
                text(surface, value, (x, y), 13, INK, anchor="topright")

        y = header_y + 26 + 3 * 30
        pygame.draw.line(surface, LINE, (self.breakdown_panel.x + 18, y - 6),
                         (self.breakdown_panel.right - 18, y - 6))
        text(surface, "Total", (self.breakdown_panel.x + 18, y), 13, INK, bold=True)
        text(surface, f'{result["score"]:.1f}',
             (self.breakdown_panel.x + 18 + 0.84 * (self.breakdown_panel.width - 36), y), 13,
             INK, bold=True, anchor="topright")

    def _footer(self, surface) -> None:
        text(surface, "Prototype indicator, not a drought prediction or official warning. "
                      "Groundwater, reservoirs and demand are not measured.",
             (28, HEIGHT - 32), 11, MUTED)
        text(surface, "1-5 city   Tab slider   arrows adjust   R reset   E save CSV   Esc quit",
             (WIDTH - 28, HEIGHT - 32), 11, MUTED, anchor="topright")


def load_cities() -> tuple[dict[str, dict], dict]:
    payload = {}
    for city in CITIES:
        path = DATA_DIR / f"{city.lower()}_daily.csv"
        if not path.exists():
            raise FileNotFoundError(path.name)
        rows = ind.load_csv(path)
        spi = ind.fit_spi_baseline(rows)
        payload[city] = {"rows": rows, "spi": spi, "heat": ind.heat_baseline(rows),
                         "history": eng.history(rows, spi)}
    first = payload[next(iter(payload))]["rows"]
    meta = {"days": len(first), "start": first[0].day.year, "end": first[-1].day.year}
    return payload, meta


def error_screen(surface, message: str) -> None:
    surface.fill(BG)
    text(surface, "OMNISIGHT", (40, 40), 30, INK, bold=True)
    text(surface, "The dashboard needs the five city CSV files.", (40, 92), 16, INK)
    text(surface, message, (40, 120), 14, MUTED)
    text(surface, "Fix it with:   python fetch_data.py", (40, 166), 15, ACCENT, bold=True)
    text(surface, "Press Esc to close.", (40, 204), 13, MUTED)


def main() -> None:
    parser = argparse.ArgumentParser(description="OMNISIGHT pygame dashboard")
    parser.add_argument("--screenshot", metavar="PATH",
                        help="render one frame to a PNG and exit")
    parser.add_argument("--rain", type=float, default=1.0, help="starting rainfall multiplier")
    parser.add_argument("--temp", type=float, default=0.0, help="starting temperature change")
    parser.add_argument("--city", default=None, help="starting city")
    args = parser.parse_args()

    pygame.init()
    pygame.display.set_caption("OMNISIGHT - water-stress indicator")
    if args.screenshot:
        Path(args.screenshot).parent.mkdir(parents=True, exist_ok=True)
    try:
        screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.SCALED | pygame.RESIZABLE)
    except pygame.error:
        screen = pygame.display.set_mode((WIDTH, HEIGHT))
    clock = pygame.time.Clock()

    screen.fill(BG)
    text(screen, "OMNISIGHT", (40, 40), 30, INK, bold=True)
    text(screen, "Loading five cities and 1991-2020 baselines...", (40, 92), 14, MUTED)
    pygame.display.flip()

    try:
        cities, meta = load_cities()
    except Exception as exc:  # missing CSV, broken CSV, unreadable file
        error_screen(screen, str(exc))
        pygame.display.flip()
        if args.screenshot:
            pygame.image.save(screen, args.screenshot)
            return
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN
                                                 and event.key == pygame.K_ESCAPE):
                    running = False
        pygame.quit()
        return

    board = Dashboard(cities, meta)
    if args.city in cities:
        board.selected = args.city
    board.rain = min(max(args.rain, 0.0), 1.5)
    board.temp = min(max(args.temp, -2.0), 5.0)

    if args.screenshot:
        board.draw(screen)
        pygame.display.flip()
        pygame.image.save(screen, args.screenshot)
        print(f"wrote {args.screenshot}")
        pygame.quit()
        return

    running = True
    while running:
        for event in pygame.event.get():
            running = board.handle(event) and running
        board.draw(screen)
        pygame.display.flip()
        clock.tick(30)

    pygame.quit()


if __name__ == "__main__":
    main()
```

### Run

```bash
python dashboard.py
```

The window opens at 1200x820 logical pixels and can be resized; pygame scales the
whole canvas, so the layout never breaks. `Esc` closes it.

Useful flags:

```bash
python dashboard.py --city Ujjain --rain 0.7 --temp 2   # start in a scenario
python dashboard.py --screenshot report.png             # one frame to PNG, then exit
```

`--screenshot` is how the report and the backup slide were produced, and it is the
only way to run the UI on a machine with no display.

### Controls

| Input | Action |
| --- | --- |
| Click a city row, or `1`-`5` | Select the city |
| Drag a slider | Apply the hypothetical rainfall / temperature change |
| `Tab`, then arrows | Adjust the active slider from the keyboard |
| `R` | Reset to real data |
| `E` | Save `data/omnisight_results.csv` |
| `Esc` or `Q` | Close |

The banner at the top right reads **REAL DATA** or **SCENARIO**, so a hypothetical
result can never be mistaken for an observation. Rows are sorted by score, and
the city rows, chips and bars are re-sorted live as the sliders move.

### What to verify

* Five cities appear, each with a score, a level chip and a bar.
* The selected row is highlighted, and `1`-`5` follow the same order.
* Selecting a city updates the score badge, the four tiles, both charts and the
  breakdown.
* Dragging the rainfall slider changes SPI-3 and the score; dragging temperature
  changes the heat z-score. The banner switches to **SCENARIO**.
* The dry-spell number does **not** change under a rainfall multiplier - dry days
  stay dry. That is correct, and it is worth explaining rather than hiding.
* `R` restores 1.00 / 0.0 °C, and the banner returns to **REAL DATA**.
* `E` writes a six-line CSV (header + five cities) next to the data.
* Nothing crashes when the window is resized.

### Design notes worth defending

* **Why pygame:** it is one package with wheels on all three desktop platforms,
  it needs no browser, no port and no server process, and it draws exactly what
  the score model returns. A judge can be shown the code for every pixel.
* **Fonts:** the code tries DejaVu, Liberation, Arial, Helvetica and FreeSans,
  then falls back to pygame's bundled font, so text renders on Windows, macOS and
  Linux without shipping a font file.
* **Colour is never the only signal:** every level also carries a text chip, and
  every chart has numeric axis labels.
* **The window is a view, not the model.** All numbers come from `risk_engine.py`,
  which is unit-tested independently, so a drawing bug cannot silently change a
  score.
* **Startup** draws a "Loading ..." frame before parsing 35 years of history for
  five cities, so the window never looks frozen.

## 8. `README.md`

````markdown
<div align="center">

# OMNISIGHT

**Weather-based water-stress risk indicator for five Madhya Pradesh cities**

![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)
![pygame](https://img.shields.io/badge/pygame-2.5%2B-2e7d32)
![License](https://img.shields.io/badge/license-MIT-2563eb)
[![Tests](https://github.com/Mimoboi/omnisight/actions/workflows/tests.yml/badge.svg)](https://github.com/Mimoboi/omnisight/actions/workflows/tests.yml)

Indore · Bhopal · Gwalior · Jabalpur · Ujjain

[Quickstart](#quickstart) · [How it works](#how-it-works) · [Data](#data) · [Limitations](#limitations)

</div>

> **Prototype, not an operational system.** OMNISIGHT compares three weather
> indicators against a 1991–2020 baseline and reports a transparent 0–100 score.
> It is not a drought prediction, an official warning, or a measurement of actual
> water scarcity. The weights and thresholds are design assumptions and have not
> been calibrated against measured water availability.

![OMNISIGHT dashboard](docs/screenshot.png)

---

## Why

Rainfall deficits, unusual heat and long dry spells are early, cheap signals that
can be compared between neighbouring cities. OMNISIGHT puts those three signals in
one window so that a difference between cities is visible, explainable and
reproducible — offline, from cached data.

## Quickstart

```bash
git clone https://github.com/Mimoboi/omnisight.git
cd omnisight
python -m pip install -r requirements.txt
python dashboard.py
```

That is the whole setup: one dependency (`pygame`), no server, no browser, no
build step. The repository already contains the cached weather data, so the
dashboard opens offline straight after cloning.

To refresh the data:

```bash
python fetch_data.py --force     # re-downloads 13,072 days per city
```

**Requirements:** Python 3.11+ and a desktop session. Windows, macOS and Linux.

## Controls

| Input | Action |
| --- | --- |
| Click a city row, or `1`–`5` | Select the city |
| Drag a slider | Apply a hypothetical rainfall / temperature change |
| `Tab`, then arrow keys | Adjust the active slider from the keyboard |
| `R` | Reset to real data |
| `E` | Export `data/omnisight_results.csv` |
| `Esc` / `Q` | Close |

The header banner switches between **REAL DATA** and **SCENARIO**, so a
hypothetical result can never be mistaken for an observation.

### Non-interactive use

```bash
python dashboard.py --city Ujjain --rain 0.7 --temp 2
python dashboard.py --screenshot report.png   # renders one frame and exits
```

`--screenshot` also lets the UI run on machines without a display, which is how
the image above was produced.

## How it works

Three indicators are computed from daily maximum temperature and rainfall, then
combined into a 0–100 score.

| Indicator | Definition |
| --- | --- |
| **SPI-3** | Rainfall over the latest three complete months, ranked against the same ending month in 1991–2020 and converted to standard-normal units. Empirical, not a gamma fit. |
| **Heat anomaly** | Trailing 30-day mean of `tmax`, expressed as a z-score against the same calendar day in 1991–2020. |
| **Dry spell** | Longest run of days below 1 mm in the latest 60 days. |

```text
rain_part = clip(-SPI3 / 2, 0, 1)
heat_part = clip(heat_z / 2, 0, 1)
dry_part  = clip(dry_days / 30, 0, 1)

score = 100 * (0.50 * rain_part + 0.25 * heat_part + 0.25 * dry_part)
```

| Score | Level |
| --- | --- |
| 0 – 25 | Low |
| 25 – 50 | Moderate |
| 50 – 75 | High |
| 75 – 100 | Very high |

Each component and its weighted points are shown in the **Why this score?**
panel, so any number on screen can be traced back to its input. A month is only
scored when it is complete; gaps in the recent window raise an error instead of
silently producing a number.

### Design decisions

- **Empirical SPI.** Ranking against 30 baseline years needs no SciPy and makes no
  distributional assumption. The trade-off is discrete values and a baseline
  standard deviation near 0.90 rather than exactly 1.00.
- **Scenarios never alter history.** A what-if change touches only the latest
  three rain months and the latest 30 temperature days, so a scenario remains
  comparable to the real baseline.
- **View and model are separate.** All numbers come from `risk_engine.py`, which is
  tested independently of pygame.

## Project structure

```text
omnisight/
├── dashboard.py            # pygame window: comparison, charts, sliders, export
├── risk_engine.py          # score, levels, scenarios, monthly history
├── indicators.py           # SPI-3, heat z-score, dry spell
├── fetch_data.py           # Open-Meteo download with retry, cached to CSV
├── requirements.txt        # pygame>=2.5
├── data/                   # cached daily CSVs (1991-01-01 → 2026-10-15)
├── docs/screenshot.png
├── tests/
│   ├── test_indicators.py  # 19 tests, no pygame needed
│   └── test_dashboard.py   # 7 UI tests, auto-skip without pygame or data
└── arctecture.md           # full build blueprint, validation log, judge Q&A
```

## Data

- **Source:** [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
  (reanalysis-based estimates, not station measurements).
- **Coverage:** daily `temperature_2m_max` and `precipitation_sum`,
  1991-01-01 → 2026-10-15, 13,072 rows per city, zero missing values.
- **Cache:** `data/<city>_daily.csv`, committed so the demo works offline. Delete
  the folder and run `fetch_data.py` to rebuild it.
- **Attribution:** weather data by Open-Meteo. Review the current
  [terms](https://open-meteo.com/en/terms) before public use.

## Testing

```bash
python -m unittest discover -s tests -v
```

26 tests, about 2 seconds. They cover month completeness, rolling windows across
year boundaries, SPI behaviour at the median and extremes, the dry-spell scan,
heat z-scores and the zero-variance guard, level boundaries, the four scenario
invariants, and the UI interactions (selection, slider drag, reset, export, exit).

The UI tests run headless via `SDL_VIDEODRIVER=dummy`, so the suite works on a CI
runner with no display:

```bash
SDL_VIDEODRIVER=dummy python -m unittest discover -s tests
```

## Limitations

- Weather indicators do **not** measure groundwater, reservoir storage, river
  flow, demand, infrastructure or supply.
- The 50/25/25 weights and the 25/50/75 cut-offs are **design assumptions**, not
  calibrated constants.
- Open-Meteo values are reanalysis estimates, not readings from a station in each
  city.
- The 2002 monsoon comparison in the blueprint is *consistent with* the documented
  deficit; the IMD citation still has to be added by the author.
- No predictive accuracy is claimed. Validation is limited to unit tests, a
  baseline sanity check (mean SPI ≈ 0.00) and that 2002 comparison.

## Roadmap

- [ ] Add a validated IMD rainfall comparison with a cited source
- [ ] Add reservoir / groundwater indicators where open data exists
- [ ] Export the evidence report as a PDF
- [ ] Optional map view with offline vector boundaries
- [ ] Sensitivity analysis of the weights

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
Please keep the scientific claims conservative: new indicators need a source and
a test.

## License

[MIT](LICENSE). Weather data remains subject to Open-Meteo's terms.

## Acknowledgements

- [Open-Meteo](https://open-meteo.com/) for free historical weather data
- [Copernicus Emergency Management Service](https://drought.emergency.copernicus.eu/)
  for the SPI methodology factsheet
- STEAM Innovation League 2.0, Indore regional round
````

## 9. Run the complete sequence

From the `omnisight` folder, in this order:

```bash
python -m pip install -r requirements.txt
python fetch_data.py
python -m unittest discover -s tests -v
python dashboard.py
```

On a machine with no display (for example over SSH), the UI tests still run and
the dashboard can still render:

```bash
SDL_VIDEODRIVER=dummy python -m unittest discover -s tests
python dashboard.py --screenshot report.png
```

### Data integrity checks (no pandas, no installs)

Row count and date range per file:

```bash
python -c "import csv,glob; [print(f, len(r:=list(csv.DictReader(open(f)))), r[0]['date'], r[-1]['date']) for f in sorted(glob.glob('data/*.csv'))]"
```

Missing values per file:

```bash
python -c "import csv,glob; [print(f, sum(1 for x in csv.DictReader(open(f)) if not x['tmax_c'] or not x['rain_mm'])) for f in sorted(glob.glob('data/*.csv'))]"
```

Verified result here: every file reports `13072 1991-01-01 2026-10-15` and `0`
missing values. If a count is non-zero, find out whether the gap touches the
latest 60 days or the baseline; the engine refuses to score rather than guess.

### Scenario sanity check

Compare the default (1.00, 0 °C) with the drier/hotter case (0.70, +2 °C). On this
data Indore moves from 31.4 to 64.4. The dry-spell number stays at 11, because
multiplying rainfall by 0.7 keeps every dry day dry. Explain that rather than
promising a bigger jump.

### Offline check

1. Install pygame and download the data while online.
2. Disconnect Wi-Fi / unplug the network.
3. Start `python dashboard.py`, select cities, drag both sliders, press `R` and `E`.

Verified: the dashboard has no network code at all - only `fetch_data.py` does -
so the window, the scoring and the CSV export all work with the network off.

### Fresh-machine check

This is the universal test that matters before the event:

1. On a different computer, install Python 3.11+ from python.org.
2. Run `python -m pip install -r requirements.txt`.
3. Copy the folder (including `data/`) and run `python dashboard.py`.

Done when it opens first time, with no missing-module message.

## 10. Validation plan - do not skip this

Judges ask "how do you know it works?". Separate code tests from real-world
validation, and only report what you actually ran.

### Check A - Unit tests

`python -m unittest discover -s tests -v` -> 15 passed. This proves the arithmetic
does what the code says. It does not prove the score measures water scarcity.

### Check B - SPI baseline sanity (completed here)

Every SPI value from 1991-2020 should be centred on zero. Measured on the
downloaded data, per city, over 358 baseline months:

| City | Baseline mean SPI | Baseline SD | Interpretation |
| --- | ---: | ---: | --- |
| Indore | +0.001 | 0.900 | centred, slightly under-dispersed |
| Bhopal | 0.000 | 0.902 | centred |
| Gwalior | 0.000 | 0.903 | centred |
| Jabalpur | 0.000 | 0.903 | centred |
| Ujjain | +0.002 | 0.899 | centred |

The mean being ~0 is a genuine check that the ranking is implemented correctly.
The SD of ~0.90 rather than 1.00 is expected for an empirical SPI with 30 baseline
years: the mid-rank plotting position deliberately compresses the tails. State
this if asked; do not claim SD = 1.

### Check C - Known dry period (partially completed)

The 2002 monsoon is one of the most widely documented all-India rainfall deficits.
OMNISIGHT, computed only from the downloaded weather, gives:

| City | Mean SPI-3, Jun-Sep 2002 | Most negative month |
| --- | ---: | ---: |
| Indore | -0.85 | -1.85 |
| Bhopal | -0.83 | -1.85 |
| Gwalior | -1.33 | -1.85 |
| Jabalpur | -0.71 | -1.85 |
| Ujjain | -0.90 | -1.85 |

Direction is consistent with a documented drought year in all five cities. To turn
this into real validation you must **add the source yourself**: an IMD or Government
of Madhya Pradesh publication with a URL, the region it covers, and the exact
months it describes. Until that citation exists, describe this as "consistent with",
not "validated against". Also compare 2024 (Jun-Sep mean SPI +0.4 to +1.3 here) as a
normal-to-wet contrast.

### Check D - Independent comparison, if feasible

If IMD sub-divisional rainfall data is accessible and its terms allow use, compare
seasonal totals for a matching region and period. Report the sample size and the
method. If you cannot do it before the event, say "validation is limited".

### Validation log to fill in

| Check | Result | Evidence | Limitation |
| --- | --- | --- | --- |
| Automated tests | 15 passed | terminal output | Code behaviour only |
| SPI baseline sanity | mean ~0, SD ~0.90 | table above | Does not validate water scarcity |
| Documented dry period | 2002 negative in all 5 cities | needs IMD URL | Regions and months may differ |
| Independent rainfall comparison | not done | - | Would be the strongest evidence |

---

## 11. Day-by-day plan (22-29 October)

The work here is already done and verified, so the remaining days are for
reproducing it on your own machine, understanding it, and rehearsing.

### 22 October - setup and data

* Install pygame, copy the five code files, run `python fetch_data.py`.
* Confirm five CSVs, 13,072 rows each, date range 1991-01-01 to 2026-10-15.
* If you hit HTTP 429, you are rate-limited; wait and rerun (the script skips
  finished cities).

Done when: five CSVs exist locally and you can state their row counts.

### 23 October - indicators and tests

* Read `indicators.py` and `risk_engine.py` line by line.
* Run the 26 tests.
* Print SPI, heat z and dry days for two cities and sanity-check the sign.

Done when: tests pass and you can explain each of the three indicators out loud.

### 24 October - dashboard

* Run `python dashboard.py` and resize the window.
* Check the city rows, the score badge, the four tiles and both charts.
* Run `python dashboard.py --screenshot report.png` and open the PNG.

Done when: all five cities appear with the same scoring date.

### 25 October - explainability and scenarios

* Walk through the "Why this score?" table and confirm the points add to the score.
* Move both sliders; confirm the SCENARIO banner and the changed ranking.
* Press `E`, then open `data/omnisight_results.csv`.

Done when: you can point at any number and say where it came from.

### 26 October - validation and limitations

* Run the baseline sanity check and the 2002 comparison (or ask me to add a script).
* Add at least one IMD/Govt source for the 2002 claim, with a URL.
* Write down what you did not validate.

Done when: you can answer "what did you test?" with evidence, and "what didn't you test?" without embarrassment.

### 27 October - reliability and freeze

* Fresh terminal, run the full sequence again.
* Airplane mode test: the window must still score, chart and export.
* Generate `report.png` and keep it as a backup artifact.
* Freeze features.

Done when: the demonstration works twice in a row, including offline.

### 28 October - rehearsal

* Three-minute pitch, timed.
* Record a backup video of the working demo.
* Copy the project folder (with `data/`) and `report.png` to a second location.

Done when: you can run the whole demo without notes.

### 29 October - event day

* Arrive with the laptop charged and pygame already installed.
* Start in REAL DATA MODE.
* Demonstrate one city, explain the score, then show one labelled scenario.
* State limitations before the judges ask.

---

## 12. Three-minute presentation plan

**0:00-0:20 - Problem.** "Rainfall deficits, unusual heat and long dry spells are
useful warning signs. Comparing them across cities shows where attention may be
needed."

**0:20-0:50 - Solution.** "OMNISIGHT compares five Madhya Pradesh cities using
historical rainfall and temperature. It combines SPI-3, a heat anomaly and dry-spell
length into an explainable 0-100 prototype score, and runs entirely offline on the
device after one download."

**0:50-2:00 - Demonstration.** Show the five-city table and chart. Pick one city,
read the three components, show that the weighted points add to the score. Move the
rainfall slider, point at the SCENARIO MODE banner, then reset.

**2:00-2:30 - Evidence.** "15 automated tests pass. The SPI baseline centres on zero
(mean 0.00). The 2002 monsoon shows a negative SPI in all five cities, consistent
with the documented deficit. We did not claim an accuracy percentage."

**2:30-3:00 - Limits and next step.** "This is not a prediction or official warning.
It ignores groundwater, reservoirs and demand, and the weights are assumptions. Next
step: validate against IMD records and add water-resource data."

---

## 13. Likely judge questions

**"Is this AI?"**
"No. It is a transparent statistical scoring model. We deliberately avoided machine
learning because there is no labelled water-scarcity dataset to train or validate on."

**"Why a plain pygame window instead of a web dashboard?"**
"One dependency and no server. A browser dashboard needs a framework and a running
process; each is a failure point in a venue. pygame ships as a single wheel on
Windows, macOS and Linux, so anyone can install it and open the window. The model,
the tests and the charts are all real; only the packaging is smaller."

**"Can I run this on my machine?"**
"Three commands: `pip install -r requirements.txt`, `python fetch_data.py`,
`python dashboard.py`. No virtualenv, no configuration, no browser."

**"Does it predict drought?"**
"No. It scores recent weather against history. It does not forecast and does not
issue warnings."

**"Is your data real?"**
"The saved series comes from the Open-Meteo Historical Weather API: 13,072 days per
city from 1991 to 2026, zero missing values. It is reanalysis-based, not a station
measurement at each city. The scenario values are hypothetical and labelled."

**"How accurate is it?"**
"We do not claim an accuracy percentage. We report 26 passing tests, a baseline mean
SPI of 0.00, and a check against the documented 2002 deficit. The remaining gap is
independent validation, which we name rather than hide."

**"Why 50/25/25?"**
"Initial design assumptions: rainfall is the dominant driver, heat and dry spells
moderate it. They are visible, adjustable in code, and not calibrated."

**"Can weather prove water scarcity?"**
"No. Groundwater, reservoir storage, river flow, demand, infrastructure and
management also matter, and none are in this prototype."

**"What is new about it?"**
"Three weather indicators, five local cities, a visible score breakdown and a
what-if comparison in one offline desktop tool. We do not claim no similar tool exists."

**"What if the internet dies?"**
"Only the first download needs it. The window reads local CSVs and contains no
network code at all, so the demo survives with Wi-Fi off. We tested that."

**"How would you improve it?"**
"Validate against IMD rainfall and water-resource records, add reservoir and
groundwater indicators, then consider prediction only once labelled data exists."

---

## 14. Troubleshooting

### `pygame is not installed`

```bash
python -m pip install -r requirements.txt
```

If pip is not on PATH on Windows, use `py -m pip install pygame`.

### `ModuleNotFoundError: No module named 'streamlit'` (or pandas, scipy)

You are running an older copy of this project. The current version needs only
pygame. Check that you are in the right folder and running `python dashboard.py`.

### A window does not appear

* The dashboard needs a **graphical desktop session**. Over SSH, in Docker, or on
  a bare server there is no display: use `--screenshot` or set
  `SDL_VIDEODRIVER=dummy` for tests.
* On Android/Termux a window needs an X server (for example termux-x11). Without
  one, run the data and tests on the phone and present from a laptop.
* If the window opens off-screen, delete any saved window position or start it
  again; pygame centres a new window by default.

### `pygame.error: No available video device`

Same cause: no display. Either run it on the desktop, or use the screenshot mode:

```bash
python dashboard.py --screenshot report.png
```

### The window is tiny or blurry on a high-DPI screen

The canvas is scaled, not re-laid-out. Maximise the window; the 1200x820 layout
grows proportionally and stays sharp because text is redrawn at the scaled size.

### `dashboard needs the five city CSV files` (red error screen)

Run `python fetch_data.py`. The app deliberately refuses to draw an incomplete
five-city comparison.

### `Latest 60 days: missing weather values`

The CSV has a gap near the end of the record. Rerun `python fetch_data.py --force`.
Do not patch the file with zeros - the engine will silently produce a wrong score.

### `No SPI baseline for ending month N`

The CSV does not contain enough of 1991-2020 for that ending month, usually
because the download was truncated. Check the row counts with the integrity
command in section 9.

### Scores look flat or identical across cities

Expected in a normal monsoon month: SPI near 0, heat z near 0, dry spell short.
Use the sliders to show sensitivity, and say plainly that the real data shows a
low-risk period.

### Dragging feels slow on an old laptop

Each frame rescoring five cities costs about 12 ms here. If a very old machine
struggles, the fix is to rescore only on mouse-up rather than every motion; the
code keeps that in one place (`handle`, the `MOUSEMOTION` branch).

### `E` says "Save failed"

The folder is read-only or the disk is full. The CSV is written next to the data
files; copy the project to a writable folder.

### Text renders as boxes on Linux

A minimal Linux install may lack any of the fallback fonts. Install one package
(`fonts-dejavu-core` on Debian/Ubuntu) or pygame's bundled font is used
automatically.

## 15. Final checklist

**Project runs**
- [ ] `python fetch_data.py` produces five CSVs, 13,072 rows each.
- [ ] `python -m unittest discover -s tests -v` reports 26 passing tests.
- [ ] `python dashboard.py` opens the window at 1200x820 and survives resizing.
- [ ] Five cities score, with the same `as_of` date.
- [ ] Sliders flip the banner to SCENARIO MODE and change the scores; Reset restores.
- [ ] `E` writes a results CSV with 6 lines.
- [ ] `report.png` exists as an offline backup.
- [ ] Airplane-mode test passes.

**Scientific honesty**
- [ ] Weights and cut-offs labelled as assumptions.
- [ ] "Not a prediction or official warning" visible in the window footer.
- [ ] Open-Meteo described as reanalysis-based, with attribution.
- [ ] Groundwater, reservoirs and demand named as missing.
- [ ] Empirical (not gamma) SPI disclosed, including SD ~0.90.
- [ ] 2002 comparison backed by a real citation, or called "consistent with".
- [ ] No accuracy percentage invented.

**Competition readiness**
- [ ] Organisers confirmed software-only eligibility.
- [ ] Rehearsed on the actual presentation laptop, from a fresh install.
- [ ] Backup: `report.png`, CSVs, and a screen recording.
- [ ] You can explain every number on screen and every number you did not validate.

---

## 16. Source and unverified items

**From the source PDF:** five cities; Open-Meteo daily max temperature and
precipitation; 1991-2020 baseline; SPI-3, 30-day heat anomaly, 60-day dry spell;
0-100 score with 50/25/25 starting weights; comparison, city detail, explanation,
what-if and evidence report; local caching; honest limitations.

**Changed deliberately in this edition:** the UI is a pygame window (Streamlit,
pandas, NumPy, SciPy, Plotly, Folium and pytest removed); SPI is empirical rather
than gamma-fitted; the map is replaced by a comparison table and bar rows; the
"evidence report" is the window, a screenshot PNG and a results CSV.

**Still unverified - do not claim otherwise:**

* The live API worked here (13,072 rows x 5 cities, zero missing), but reanalysis
  data is not a station measurement.
* Event rules, software-only eligibility, venue network and power.
* Official validation of the weights and thresholds - none exists.
* Specific documented MP drought periods - the 2002 check needs a citation added.
* IMD data availability, licence and comparability.
* Any predictive accuracy.

**References**

* Open-Meteo Historical Weather API: https://open-meteo.com/en/docs/historical-weather-api
* Open-Meteo terms: https://open-meteo.com/en/terms
* Copernicus SPI factsheet: https://drought.emergency.copernicus.eu/data/factsheets/factsheet_spi.pdf
* NASA POWER daily API (alternative source): https://power.larc.nasa.gov/docs/services/api/temporal/daily/
* IMD sub-divisional monthly rainfall: https://data.gov.in/resource/sub-divisional-monthly-rainfall-1901-2017

Build principle: make the smallest complete version work first. Reliable real data,
correct calculations, a clear score explanation, a tested what-if scenario and honest
limitations are worth more than extra features that fail during judging.
