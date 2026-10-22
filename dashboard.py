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
