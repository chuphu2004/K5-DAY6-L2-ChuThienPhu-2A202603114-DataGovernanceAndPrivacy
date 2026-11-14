"""T09 baseline, wrong on purpose: "consent obtained -> GO, otherwise HOLD" (docs/tracks/T09.md §4).

Shows that a consent-only checklist misses cross-border, DPIA, retention and VN lawful-basis risks.
    python -m src.main --track t09 --pipeline src.baseline_t09 --output out/baseline --run-name baseline --offline
"""
from __future__ import annotations

import pandas as pd

from .common.context import RunContext
from .common.decision import Decision, write_decision
from .pipeline import load


def write_baseline(ctx: RunContext, rows: list[dict], name: str) -> None:
    df = pd.DataFrame(rows)
    df.to_csv(ctx.out("decisions.csv"), index=False)
    ctx.stats["n_items"] = len(df)
    write_decision(Decision(status="HOLD", reason_code="BASELINE_ONLY", reason=f"{name} baseline: never release on this",
                            owner=ctx.config.get("owner", "baseline"), scope=ctx.track, evidence=[str(ctx.out("decisions.csv"))]),
                   ctx.out("decision.json"), ctx.out("decision_log.csv"))


def run(ctx: RunContext) -> None:
    write_baseline(ctx, [{"case_id": c["case_id"], "market": c["market"],
                          "decision": "GO" if c["consent"]["obtained"] else "HOLD",
                          "reason_codes": "" if c["consent"]["obtained"] else "NO_LAWFUL_BASIS"} for c in load(ctx)["cases"]],
                   "Consent-only")
