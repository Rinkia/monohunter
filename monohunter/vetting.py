"""Crowd vetting UI — a static page for humans to label candidates.

Phase 3 starts here: real progress needs human-labelled diagnostics, and the
labels have to exist BEFORE an ML triage classifier can train on them. This is
the label factory — deliberately backend-free (same as the leaderboard): a
static HTML page shows each candidate's diagnostic PNG plus its stats and a row
of label buttons. Votes live in the browser's localStorage and export to a JSON
the volunteer submits by PR into labels/, exactly like the contributions/ flow.
No server to run, nothing to keep alive until a crowd actually shows up.

    record JSONs + PNGs  ->  build_vetting_site  ->  out/index.html + copied PNGs
      volunteer clicks a label per card  ->  localStorage  ->  Export -> labels.json

build_vetting_html is pure (takes candidate dicts) so it unit-tests offline;
build_vetting_site does the file IO.
"""

from __future__ import annotations

import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

# (value, button label) — the value is what lands in the exported labels JSON and
# later trains the classifier; keep the set small and unambiguous.
LABELS = [
    ("planet", "🪐 Planet-like"),
    ("eclipsing_binary", "⭐ Eclipsing binary"),
    ("systematic", "⚠ Systematic / junk"),
    ("noise", "〜 Noise"),
    ("unsure", "? Unsure"),
]


def _card(c: dict) -> str:
    tic, sector = int(c["tic"]), int(c["sector"])
    key = f"{tic}_{sector}"
    badges = ""
    if c.get("known_toi_id"):
        badges += f'<span class="known">{html.escape(str(c["known_toi_id"]))}</span> '
    else:
        badges += '<span class="novel">NEW</span> '
    if c.get("likely_eb"):
        badges += '<span class="eb">EB?</span> '
    period = f'~{round(c["period_d"])}d' if c.get("period_d") else "—"
    buttons = "".join(
        f'<button data-key="{key}" data-label="{val}" '
        f'onclick="vote(this)">{html.escape(txt)}</button>'
        for val, txt in LABELS
    )
    png = html.escape(str(c.get("png", "")))
    return f"""<div class="card" data-key="{key}">
  <div class="hdr">{badges}<b>TIC {tic}</b> · S{sector}</div>
  <img loading="lazy" src="{png}" alt="TIC {tic} S{sector} light curve">
  <div class="stats">depth {c.get('depth_ppt', 0):.2f} ppt ·
    dur {c.get('duration_hr', 0):.0f} h · SNR {c.get('snr', 0):.1f} · P {period}</div>
  <div class="labels">{buttons}</div>
</div>"""


def build_vetting_html(candidates: list[dict], title: str = "monohunter — vet candidates") -> str:
    """Static vetting page: a labelled card per candidate. Pure (no file IO)."""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cards = "\n".join(_card(c) for c in candidates) or "<p>No candidates to vet.</p>"
    return _TEMPLATE.format(
        title=html.escape(title), generated=generated, count=len(candidates), cards=cards
    )


def build_vetting_site(candidates_dir: str | Path, out_dir: str | Path) -> int:
    """Load record JSONs + their PNGs from candidates_dir, copy the PNGs into
    out_dir, and write index.html. Returns the number of cards. File IO."""
    from .record import FindRecord

    src = Path(candidates_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    cards: list[dict] = []
    for jpath in sorted(src.glob("*.json")):
        try:
            rec = FindRecord(**json.loads(jpath.read_text(encoding="utf-8")))
        except Exception:
            continue
        png = src / f"tic{rec.tic}_s{rec.sector}.png"
        if not png.exists():
            continue  # a card without its diagnostic image is not vettable
        shutil.copy(png, out / png.name)
        cards.append({
            "tic": rec.tic, "sector": rec.sector, "png": png.name,
            "depth_ppt": rec.depth_ppt, "duration_hr": rec.duration_hr, "snr": rec.snr,
            "period_d": rec.p_best_d if rec.period_constrained else None,
            "likely_eb": bool(rec.likely_eb), "known_toi_id": rec.known_toi_id,
        })
    (out / "index.html").write_text(build_vetting_html(cards), encoding="utf-8")
    return len(cards)


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 1.5rem auto; max-width: 820px; padding: 0 1rem; color: #1a1a1a; }}
  h1 {{ margin-bottom: .2rem; }}
  .meta {{ color: #666; margin-bottom: 1rem; }}
  .bar {{ position: sticky; top: 0; background: #fff; padding: .6rem 0; border-bottom: 1px solid #eee; }}
  .bar input {{ padding: .3rem .5rem; }}
  .card {{ border: 1px solid #e5e5e5; border-radius: 8px; padding: 1rem; margin: 1rem 0; }}
  .card img {{ width: 100%; height: auto; border-radius: 4px; }}
  .hdr {{ margin-bottom: .5rem; }}
  .stats {{ color: #555; font-size: 13px; margin: .5rem 0; }}
  .labels button {{ margin: .2rem .3rem .2rem 0; padding: .4rem .6rem; border: 1px solid #ccc;
    border-radius: 5px; background: #fafafa; cursor: pointer; font-size: 14px; }}
  .labels button.chosen {{ background: #0a7d2c; color: #fff; border-color: #0a7d2c; }}
  .novel {{ background: #0a7d2c; color: #fff; padding: .1rem .4rem; border-radius: 3px; font-size: 12px; font-weight: 600; }}
  .known {{ background: #eee; color: #555; padding: .1rem .4rem; border-radius: 3px; font-size: 12px; }}
  .eb {{ background: #b8860b; color: #fff; padding: .1rem .4rem; border-radius: 3px; font-size: 12px; }}
  #count {{ font-weight: 600; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="meta">{count} candidates · generated {generated} · a candidate is not a
confirmed planet — your label helps triage it.</p>
<div class="bar">
  your name: <input id="voter" placeholder="handle" oninput="save('mh_voter', this.value)">
  <button onclick="exportLabels()">⬇ Export labels</button>
  <span id="count">0 labelled</span>
</div>
{cards}
<script>
  const KEY = "monohunter_labels";
  const load = () => JSON.parse(localStorage.getItem(KEY) || "{{}}");
  const save = (k, v) => localStorage.setItem(k, v);
  function refresh() {{
    const votes = load();
    document.querySelectorAll(".card").forEach(card => {{
      const k = card.dataset.key, chosen = votes[k] && votes[k].label;
      card.querySelectorAll("button").forEach(b =>
        b.classList.toggle("chosen", b.dataset.label === chosen));
    }});
    document.getElementById("count").textContent =
      Object.keys(votes).length + " labelled";
  }}
  function vote(btn) {{
    const votes = load(), k = btn.dataset.key, [tic, sector] = k.split("_");
    votes[k] = {{ tic: +tic, sector: +sector, label: btn.dataset.label,
      ts: new Date().toISOString() }};
    localStorage.setItem(KEY, JSON.stringify(votes));
    refresh();
  }}
  function exportLabels() {{
    const votes = load(), voter = localStorage.getItem("mh_voter") || "anon";
    const rows = Object.values(votes).map(v => ({{ ...v, voter }}));
    const blob = new Blob([JSON.stringify(rows, null, 2)], {{ type: "application/json" }});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "labels_" + voter + ".json";
    a.click();
  }}
  document.getElementById("voter").value = localStorage.getItem("mh_voter") || "";
  refresh();
</script>
</body>
</html>
"""
