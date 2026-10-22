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
