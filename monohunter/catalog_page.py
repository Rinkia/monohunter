"""Render a stellar-variability catalog CSV into a static Pages view.

The sweep's summary side-product (rotation / variability / flares / dippers) is a
real catalog for scientists. This renders a committed catalog CSV into a static
HTML page — a class breakdown plus the strongest rotators / variables / flare
stars, with the full CSV linked for download. Reads the CSV directly (no pydantic
per row) so it stays fast for tens of thousands of stars.

    catalogs/sector<N>.csv  ->  render_catalog_html  ->  _site/catalog.html + CSV

render_catalog_html is pure (takes rows) and unit-tested; load_catalog is the IO.
"""

from __future__ import annotations

import csv
import html
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_CLASS_ORDER = ("rotator", "variable", "flaring", "dipper", "quiet")


def load_catalog(csv_path: str | Path) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _f(row: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(row[key])
    except (KeyError, ValueError, TypeError):
        return default


def _top(rows: list[dict], cls: str, sort_key: str, n: int = 15) -> list[dict]:
    sub = [r for r in rows if r.get("var_class") == cls]
    sub.sort(key=lambda r: -_f(r, sort_key))
    return sub[:n]


def _rows_html(rows: list[dict], cols) -> str:
    out = []
    for r in rows:
        cells = "".join(f"<td>{html.escape(str(fmt(r)))}</td>" for _h, fmt in cols)
        out.append(f"<tr>{cells}</tr>")
    return "\n".join(out) or f'<tr><td colspan="{len(cols)}">none</td></tr>'


def render_catalog_html(rows: list[dict], sector: int, csv_name: str) -> str:
    """Static catalog page from CSV rows. Pure (no file IO)."""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    counts = Counter(r.get("var_class", "quiet") for r in rows)
    chips = " ".join(
        f'<span class="chip {c}">{c}: {counts.get(c, 0)}</span>' for c in _CLASS_ORDER
    )

    rot_cols = [
        ("TIC", lambda r: r["tic"]),
        ("P_rot (d)", lambda r: f'{_f(r, "rotation_period_d"):.2f}'),
        ("power", lambda r: f'{_f(r, "rotation_power"):.2f}'),
        ("amp (ppt)", lambda r: f'{_f(r, "var_amplitude_ppt"):.1f}'),
    ]
    var_cols = [
        ("TIC", lambda r: r["tic"]),
        ("amp (ppt)", lambda r: f'{_f(r, "var_amplitude_ppt"):.1f}'),
    ]
    flare_cols = [
        ("TIC", lambda r: r["tic"]),
        ("flares", lambda r: r["n_flares"]),
        ("amp (ppt)", lambda r: f'{_f(r, "var_amplitude_ppt"):.1f}'),
    ]
    return _TEMPLATE.format(
        sector=sector, generated=generated, total=len(rows), chips=chips,
        csv_name=html.escape(csv_name),
        rot_head="".join(f"<th>{h}</th>" for h, _ in rot_cols),
        rot_rows=_rows_html(_top(rows, "rotator", "rotation_power"), rot_cols),
        var_head="".join(f"<th>{h}</th>" for h, _ in var_cols),
        var_rows=_rows_html(_top(rows, "variable", "var_amplitude_ppt"), var_cols),
        flare_head="".join(f"<th>{h}</th>" for h, _ in flare_cols),
        flare_rows=_rows_html(_top(rows, "flaring", "n_flares"), flare_cols),
    )


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>monohunter — Sector {sector} variability catalog</title>
<style>
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 900px; padding: 0 1rem; color: #1a1a1a; }}
  h1 {{ margin-bottom: .2rem; }} h2 {{ margin-top: 2rem; }}
  .meta {{ color: #666; margin-bottom: 1rem; }}
  .chip {{ display: inline-block; padding: .15rem .5rem; border-radius: 4px; margin: .15rem .2rem; font-size: 13px; background: #eee; }}
  .chip.rotator {{ background: #0a7d2c; color: #fff; }}
  .chip.variable {{ background: #2b6cb0; color: #fff; }}
  .chip.flaring {{ background: #b8860b; color: #fff; }}
  .chip.dipper {{ background: #7a3fbf; color: #fff; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: .5rem; }}
  th, td {{ text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #eee; }}
  th {{ font-size: 13px; text-transform: uppercase; color: #888; }}
  a {{ color: #0a5; }}
</style>
</head>
<body>
<h1>monohunter — Sector {sector} variability catalog</h1>
<p class="meta">{total} stars · generated {generated} · a by-product of the transit
sweep, from the same downloads · <a href="{csv_name}">download full CSV</a> ·
<a href="index.html">leaderboard</a></p>
<p>{chips}</p>
<p class="meta">Rotation periods from Lomb-Scargle on the raw (un-transit-detrended)
flux; instrumental periods (~13.7 d TESS orbit, 1 d, longer than the baseline) are
excluded. A period here is a candidate — worth a phased look before use.</p>

<h2>Strongest rotators</h2>
<table><thead><tr>{rot_head}</tr></thead><tbody>{rot_rows}</tbody></table>

<h2>Largest-amplitude variables</h2>
<table><thead><tr>{var_head}</tr></thead><tbody>{var_rows}</tbody></table>

<h2>Most active flare stars</h2>
<table><thead><tr>{flare_head}</tr></thead><tbody>{flare_rows}</tbody></table>
</body>
</html>
"""
