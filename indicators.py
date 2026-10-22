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
