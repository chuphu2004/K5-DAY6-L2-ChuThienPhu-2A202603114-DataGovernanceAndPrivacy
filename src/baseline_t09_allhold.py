"""T09 trivial baseline: HOLD every case. Critical-miss 0 but fails the false-HOLD guardrail (docs/tracks/T09.md §3).
    python -m src.main --track t09 --pipeline src.baseline_t09_allhold --output out/baseline_allhold --run-name baseline_allhold --offline
"""
from __future__ import annotations

from .baseline_t09 import write_baseline
from .common.context import RunContext
from .pipeline import load


def run(ctx: RunContext) -> None:
    write_baseline(ctx, [{"case_id": c["case_id"], "market": c["market"], "decision": "HOLD",
                          "reason_codes": "AMBIGUOUS_NEEDS_LEGAL"} for c in load(ctx)["cases"]], "All-HOLD")
