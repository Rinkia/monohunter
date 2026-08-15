"""Aggregate community find-records into a ranked candidate leaderboard.

Input layout (from the contributions/ PR flow):

    contributions/<submitter>/tic<TIC>_s<SECTOR>.json

Records for the same (tic, sector) from different submitters are grouped. A
candidate flagged by more independent people, that is NOT already a known TOI,
with higher SNR, ranks higher — that ordering is the whole value of the swarm.
"""

from __future__ import annotations

import html
import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ..record import FindRecord


@dataclass
class _Submission:
    submitter: str
    record: FindRecord


@dataclass
class AggregatedCandidate:
    tic: int
    sector: int
    submitters: list[str] = field(default_factory=list)
    best_snr: float = 0.0
    median_depth_ppt: float = 0.0
    median_duration_hr: float = 0.0
    known_toi_match: bool = False
    known_toi_id: str | None = None
    p_best_d: float | None = None          # best submitter's period estimate
    likely_eb: bool = False                # depth-flagged eclipsing binary

    @property
    def n_submitters(self) -> int:
        return len(self.submitters)

    @property
    def novel(self) -> bool:
        """Not a known TOI — the interesting, potentially-unsearched case."""
        return not self.known_toi_match

    def sort_key(self) -> tuple:
        # novel first, then more submitters, then higher SNR.
        return (not self.novel, -self.n_submitters, -self.best_snr)


def load_records(contributions_dir: str | Path) -> list[_Submission]:
    """Load every contributions/<submitter>/*.json as a validated FindRecord.

    Invalid or unreadable files are skipped (bad submissions shouldn't break the
    whole leaderboard).
    """
    root = Path(contributions_dir)
    submissions: list[_Submission] = []
    for path in sorted(root.glob("*/*.json")):
        submitter = path.parent.name
        try:
            record = FindRecord(**json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        submissions.append(_Submission(submitter=submitter, record=record))
    return submissions


def aggregate(submissions: list[_Submission]) -> list[AggregatedCandidate]:
    """Group submissions by (tic, sector) and rank them."""
    groups: dict[tuple[int, int], list[_Submission]] = {}
    for sub in submissions:
        key = (sub.record.tic, sub.record.sector)
        groups.setdefault(key, []).append(sub)

    candidates: list[AggregatedCandidate] = []
    for (tic, sector), subs in groups.items():
        recs = [s.record for s in subs]
        submitters = sorted({s.submitter for s in subs})
        best_rec = max(recs, key=lambda r: r.snr)
        candidates.append(
            AggregatedCandidate(
                tic=tic,
                sector=sector,
                submitters=submitters,
                best_snr=best_rec.snr,
                median_depth_ppt=statistics.median(r.depth_ppt for r in recs),
                median_duration_hr=statistics.median(r.duration_hr for r in recs),
                known_toi_match=any(r.known_toi_match for r in recs),
                known_toi_id=next((r.known_toi_id for r in recs if r.known_toi_id), None),
                p_best_d=best_rec.p_best_d if best_rec.period_constrained else None,
                likely_eb=any(bool(r.likely_eb) for r in recs),
            )
        )

    candidates.sort(key=AggregatedCandidate.sort_key)
    return candidates


def render_json(candidates: list[AggregatedCandidate]) -> str:
    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "count": len(candidates),
        "candidates": [
            {
                "tic": c.tic,
                "sector": c.sector,
                "novel": c.novel,
                "n_submitters": c.n_submitters,
                "submitters": c.submitters,
                "best_snr": round(c.best_snr, 1),
                "median_depth_ppt": round(c.median_depth_ppt, 2),
                "median_duration_hr": round(c.median_duration_hr, 1),
                "period_d": round(c.p_best_d) if c.p_best_d else None,
                "likely_eb": c.likely_eb,
                "known_toi_id": c.known_toi_id,
            }
            for c in candidates
        ],
    }
    return json.dumps(payload, indent=2)


def render_html(candidates: list[AggregatedCandidate]) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = []
    for c in candidates:
        badge = (
            '<span class="novel">NEW</span>'
            if c.novel
            else f'<span class="known">{html.escape(c.known_toi_id or "known")}</span>'
        )
        if c.likely_eb:
            badge += ' <span class="eb">EB?</span>'
        rows.append(
            "<tr>"
            f"<td>{badge}</td>"
            f"<td>{c.tic}</td>"
            f"<td>{c.sector}</td>"
            f"<td>{c.n_submitters}</td>"
            f"<td>{c.best_snr:.1f}</td>"
            f"<td>{c.median_depth_ppt:.2f}</td>"
            f"<td>{c.median_duration_hr:.1f}</td>"
            f"<td>{('~%d' % c.p_best_d) if c.p_best_d else '—'}</td>"
            f"<td>{html.escape(', '.join(c.submitters))}</td>"
            "</tr>"
        )
    body = "\n".join(rows) or '<tr><td colspan="9">No candidates yet.</td></tr>'
    return _HTML_TEMPLATE.format(
        generated=generated, count=len(candidates), rows=body, version=__version__
    )


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>monohunter — community candidates</title>
<style>
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 900px; padding: 0 1rem; color: #1a1a1a; }}
  h1 {{ margin-bottom: .2rem; }}
  .meta {{ color: #666; margin-bottom: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: .5rem .6rem; border-bottom: 1px solid #eee; }}
  th {{ font-size: 13px; text-transform: uppercase; letter-spacing: .03em; color: #888; }}
  .novel {{ background: #0a7d2c; color: #fff; padding: .1rem .4rem; border-radius: 3px; font-size: 12px; font-weight: 600; }}
  .known {{ background: #eee; color: #555; padding: .1rem .4rem; border-radius: 3px; font-size: 12px; }}
  .eb {{ background: #b8860b; color: #fff; padding: .1rem .4rem; border-radius: 3px; font-size: 12px; }}
  a {{ color: #0a5; }}
  .release {{ background: #0a7d2c; color: #fff; padding: .6rem .9rem; border-radius: 6px;
    margin-bottom: 1.2rem; font-size: 14px; }}
  .release a {{ color: #fff; text-decoration: underline; }}
  .release code {{ background: rgba(255,255,255,.2); padding: .05rem .3rem; border-radius: 3px; }}
</style>
</head>
<body>
<h1>monohunter — community candidates</h1>
<div class="release">🚀 <b>monohunter {version} released</b> —
<code>pip install monohunter</code>. New: eclipsing-binary orbital periods from
in-sector eclipses, rotation-period distribution plots, and pulsator/rotator/
eclipsing sub-classification via periodogram harmonics.
<a href="https://github.com/Rinkia/monohunter/blob/main/CHANGELOG.md">changelog</a>
· <a href="https://pypi.org/project/monohunter/">PyPI</a></div>
<p class="meta">{count} candidates · generated {generated} ·
<a href="catalog_s15.html">variability catalog</a> ·
<a href="https://github.com/Rinkia/monohunter">contribute</a></p>
<table>
<thead><tr>
<th>status</th><th>TIC</th><th>sector</th><th>submitters</th>
<th>best SNR</th><th>depth (ppt)</th><th>dur (h)</th><th>P (d)</th><th>who</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
<p class="meta">NEW = not a known TESS Object of Interest. EB? = too deep for a
planet, likely an eclipsing binary. A candidate is not a confirmed planet — it
needs follow-up.</p>
</body>
</html>
"""
