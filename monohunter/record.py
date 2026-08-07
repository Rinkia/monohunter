"""T1 — the find-record: MonoHunter's output unit and the Swarm aggregation contract.

Versioned + validated (design decision 2A). `schema_version` travels with every
record so a future Swarm server can migrate old contributor files. `extra="forbid"`
makes a typo'd or drifted field a hard error at write time, not a silent mismatch
that only surfaces when 100 people's JSON files fail to merge.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 5  # v5 adds multi-sector context (n_sectors_observed, recurring_dip)


class FindRecord(BaseModel):
    """One candidate mono-transit, ready to serialize to JSON."""

    model_config = ConfigDict(extra="forbid")  # reject unknown/drifted fields

    schema_version: int = SCHEMA_VERSION
    tic: int = Field(..., description="TESS Input Catalog id of the target")
    sector: int
    cadence_s: int = Field(..., description="120 (2-min) or 20 (20-sec)")
    event_time_btjd: float = Field(..., description="dip center, TESS BTJD")
    depth_ppt: float = Field(..., ge=0, description="transit depth, parts per thousand")
    duration_hr: float = Field(..., gt=0, description="T14, first-to-last contact")
    ingress_hr: float | None = Field(
        None, description="ingress/egress time from trapezoid fit; None if uncharacterized"
    )
    snr: float = Field(..., ge=0)
    detrend_method: str
    detrend_window_d: float = Field(..., gt=0)
    tool_version: str
    known_toi_match: bool = False
    known_toi_id: str | None = None
    plot_path: str | None = None
    likely_eb: bool | None = None      # depth too deep for a planet → eclipsing binary

    # v3 ephemeris (present when the period could be constrained)
    stellar_density_cgs: float | None = None
    period_constrained: bool | None = None
    p_min_d: float | None = None
    p_best_d: float | None = None
    p_lo_d: float | None = None            # 16th percentile
    p_hi_d: float | None = None            # 84th percentile
    next_window_btjd: list[float] | None = None  # [5%, 50%, 95%] of next transit

    # v5 multi-sector context
    n_sectors_observed: int | None = None   # sectors searched for this target
    recurring_dip: bool | None = None        # dips in >1 sector -> periodic/variable,
    # not a clean single transit; the period is constrained by the FULL multi-sector
    # baseline (a 2nd transit ruled out across all observed sectors raises p_min)

    def to_json(self, **kwargs: object) -> str:
        return self.model_dump_json(**kwargs)  # type: ignore[arg-type]
