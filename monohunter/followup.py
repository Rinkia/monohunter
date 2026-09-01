"""Follow-up tracking — the confirmation half of a discovery.

A candidate is not a discovery; it needs external follow-up (a second transit to pin the
period, radial velocity to weigh the companion). This tracks that lifecycle as structured,
git-friendly per-target records so a community can see what is pending, being observed,
confirmed, or ruled out — closing the loop `observe` opens (observe says WHEN to point;
this records the OUTCOME).

    pending -> observing -> confirmed | rejected   (planet / EB / false-positive)

Pure state model + JSON store (mirrors contributions/): FollowupRecord is validated,
transitions are checked, and everything is immutable-update. Offline — no network.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

FOLLOWUP_SCHEMA_VERSION = 1

# Lifecycle states and the transitions allowed between them. A confirmed/rejected target
# is terminal but can reopen (new data can overturn a call), so terminals -> observing.
STATUSES = ("pending", "observing", "confirmed", "rejected")
_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"observing", "confirmed", "rejected"},
    "observing": {"confirmed", "rejected", "pending"},
    "confirmed": {"observing", "rejected"},
    "rejected": {"observing", "pending"},
}
# What the target turned out to be (free-ish, but these are the expected kinds).
KINDS = ("planet_candidate", "eclipsing_binary", "brown_dwarf", "false_positive", "other")


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_valid_transition(old: str, new: str) -> bool:
    """True if status `old` may move to `new` (same status is always allowed)."""
    if new not in STATUSES:
        return False
    if old == new:
        return True
    return new in _TRANSITIONS.get(old, set())


class FollowupRecord(BaseModel):
    """One tracked follow-up target — the confirmation state of a candidate."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = FOLLOWUP_SCHEMA_VERSION
    tic: int = Field(..., description="TESS Input Catalog id")
    sector: int
    status: str = "pending"
    kind: str = "planet_candidate"
    observer: str | None = None                      # who is following it up
    next_window_btjd: list[float] | None = None      # predicted next-transit window (from a record)
    notes: list[str] = Field(default_factory=list)   # dated log lines
    created_utc: str = Field(default_factory=_now_utc)
    updated_utc: str = Field(default_factory=_now_utc)

    def to_json(self, **kwargs: object) -> str:
        return self.model_dump_json(**kwargs)  # type: ignore[arg-type]


def new_followup(
    tic: int, sector: int, *, kind: str = "planet_candidate", status: str = "pending",
    observer: str | None = None, next_window_btjd: list[float] | None = None,
    note: str | None = None,
) -> FollowupRecord:
    """Create a follow-up record. An initial note is prefixed with the UTC timestamp."""
    notes = [f"{_now_utc()}  {note}"] if note else []
    return FollowupRecord(
        tic=int(tic), sector=int(sector), kind=kind, status=status,
        observer=observer, next_window_btjd=next_window_btjd, notes=notes,
    )


def apply_update(
    rec: FollowupRecord, *, status: str | None = None, note: str | None = None,
    observer: str | None = None,
) -> FollowupRecord:
    """Return an updated copy: change status (validated), append a dated note, set the
    observer, and stamp updated_utc. Raises ValueError on an illegal status transition."""
    updates: dict = {"updated_utc": _now_utc()}
    if status is not None:
        if not is_valid_transition(rec.status, status):
            raise ValueError(f"illegal transition {rec.status!r} -> {status!r}")
        updates["status"] = status
    if observer is not None:
        updates["observer"] = observer
    if note or status is not None:
        line = note or (f"status -> {status}" if status else "")
        updates["notes"] = [*rec.notes, f"{_now_utc()}  {line}"]
    return rec.model_copy(update=updates)


# ---- JSON store (git-friendly per-target files, like contributions/) -----

def _path(followups_dir, tic: int, sector: int):
    from pathlib import Path

    return Path(followups_dir) / f"tic{int(tic)}_s{int(sector)}.json"


def save_followup(followups_dir, rec: FollowupRecord) -> str:
    from pathlib import Path

    d = Path(followups_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = _path(d, rec.tic, rec.sector)
    p.write_text(rec.to_json(indent=2), encoding="utf-8")
    return str(p)


def load_followup(followups_dir, tic: int, sector: int) -> FollowupRecord | None:
    p = _path(followups_dir, tic, sector)
    if not p.exists():
        return None
    return FollowupRecord.model_validate_json(p.read_text(encoding="utf-8"))


def load_all(followups_dir) -> list[FollowupRecord]:
    """Every follow-up record in the directory, newest-updated first. Skips bad files."""
    from pathlib import Path

    out: list[FollowupRecord] = []
    for p in sorted(Path(followups_dir).glob("tic*_s*.json")):
        try:
            out.append(FollowupRecord.model_validate_json(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return sorted(out, key=lambda r: r.updated_utc, reverse=True)
