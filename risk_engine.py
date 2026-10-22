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
