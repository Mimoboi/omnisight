# Contributing to OMNISIGHT

Thanks for taking a look. This is a small, deliberately boring codebase: plain
Python, one dependency, no framework. Please keep it that way.

## Setup

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python dashboard.py
```

## Ground rules

1. **The model must stay explainable.** No black-box model, no hidden weights.
   Every number on screen must be traceable to an input.
2. **Do not overstate the science.** OMNISIGHT is a prototype indicator, not a
   drought prediction or an official warning. New claims need a source.
3. **A change to a calculation needs a test.** Add it to
   `tests/test_indicators.py`; the suite runs without a display.
4. **A change to the UI needs a test** in `tests/test_dashboard.py`, and the tests
   must still pass headless (`SDL_VIDEODRIVER=dummy`).
5. **No new dependencies** unless there is no standard-library alternative.
   `pygame` is the only allowed third-party package.
6. **Never edit `data/*.csv` by hand.** Regenerate with `python fetch_data.py
   --force`; a hand-patched file makes every score unreproducible.

## Style

- Python 3.11+, type hints on public functions, `from __future__ import annotations`.
- Keep modules focused: data in `fetch_data.py`, maths in `indicators.py`,
  scoring in `risk_engine.py`, drawing in `dashboard.py`.
- British spelling in prose, ASCII in code.

## Pull requests

- One logical change per pull request, with a short explanation of *why*.
- Run the full suite before opening it.
- If the change affects a displayed number, say which city and period changed and
  why that is correct.
- If you regenerate the data, note the download date in the pull request.

## Reporting issues

Include the Python and pygame versions, the operating system, the exact command,
and the full traceback. If a score looks wrong, include the city, the
`as_of` date and the three indicator values shown in the window.

## Data and attribution

Weather data is fetched from Open-Meteo and remains subject to
[its terms](https://open-meteo.com/en/terms). Do not commit data from a different
source without documenting the licence and the retrieval date.
