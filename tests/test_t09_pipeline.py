"""T09 policy engine: end-to-end run, rule DSL safety, effective_date, human review overrides."""
import json

import pandas as pd
import pytest

from src import main as runner
from src.pipeline import compile_rule, evaluate_case, load_policy
from pathlib import Path

POLICY = load_policy(Path("configs/policy/t09_policy.yaml"))
CASES = {p.stem: json.loads(p.read_text()) for p in Path("fixtures/t09_privacy_gate/cases").glob("CASE-*.json")}


def _run(out, *extra):
    return runner.main(["--track", "t09", "--output", str(out), "--offline", "--seed", "42", *extra])


def test_end_to_end_outputs_and_failure_modes(tmp_path):
    assert _run(tmp_path) == 0
    d = pd.read_csv(tmp_path / "decisions.csv").set_index("case_id")
    assert len(d) == 12 and set(d.decision) <= {"GO", "HOLD", "REWORK"}
    # failure mode: consent present but cross-border risk -> must not be GO
    assert d.loc["CASE-02", "decision"] == "HOLD" and "XBORDER_NO_MECHANISM" in d.loc["CASE-02", "reason_codes"]
    assert d.loc["CASE-07", "decision"] == "HOLD" and "XBORDER_NO_IMPACT_ASSESSMENT" in d.loc["CASE-07", "reason_codes"]
    # VN has no legitimate-interest basis
    assert "NO_LAWFUL_BASIS" in d.loc["CASE-01", "reason_codes"]
    for f in ["checklist.csv", "review_queue.csv", "contact_sheet.html", "audit_log.jsonl", "decision.json"]:
        assert (tmp_path / f).exists(), f
    # same seed -> identical decisions
    assert _run(tmp_path / "again") == 0
    assert (tmp_path / "decisions.csv").read_text() == (tmp_path / "again" / "decisions.csv").read_text()


@pytest.mark.parametrize("expr", ["__import__('os').system('id')", "open('x')", "storage.__class__"])
def test_rule_dsl_rejects_code(expr):
    with pytest.raises(ValueError):
        compile_rule(expr)


def test_future_effective_rule_is_upcoming_not_violation():
    r = evaluate_case(dict(CASES["CASE-09"], ambiguity_notes="", minors_possible=False), POLICY, "2026-11-14")
    assert r["decision"] == "GO" and "R-IN-CREC" in r["upcoming"]
    r = evaluate_case(dict(CASES["CASE-09"], ambiguity_notes="", minors_possible=False), POLICY, "2027-06-01")
    assert r["decision"] == "REWORK" and "CONSENT_RECORD_MISSING" in r["reason_codes"]


def test_uncovered_market_holds():
    assert evaluate_case(dict(CASES["CASE-06"], market="BR"), POLICY, "2026-11-14")["decision"] == "HOLD"


def _reviewed(out, rows):
    q = pd.read_csv(out / "review_queue.csv", dtype=str).fillna("")
    for item, who, dec, val in rows:
        q.loc[q.item_id == item, ["reviewer", "reviewer_decision", "override_value"]] = [who, dec, val]
    q.to_csv(out / "review_queue_reviewed.csv", index=False)


def test_review_override_is_applied_and_audited(tmp_path):
    assert _run(tmp_path) == 0
    _reviewed(tmp_path, [("CASE-06", "DPO", "edit", "REWORK"), ("CASE-01", "DPO", "approve", "")])
    assert _run(tmp_path) == 0
    d = pd.read_csv(tmp_path / "decisions.csv").set_index("case_id")
    assert d.loc["CASE-06", "decision"] == "REWORK" and d.loc["CASE-06", "auto_decision"] == "GO"
    log = [json.loads(x) for x in (tmp_path / "audit_log.jsonl").read_text().splitlines()]
    assert any(e["action"] == "review:edit" and e["item_id"] == "CASE-06" and e["actor"] == "DPO" for e in log)


def test_review_bad_override_fails_loudly(tmp_path):
    assert _run(tmp_path) == 0
    _reviewed(tmp_path, [("CASE-06", "DPO", "edit", "MAYBE")])
    assert _run(tmp_path) == 2


def test_consent_only_baseline_misses_xborder(tmp_path):
    assert _run(tmp_path, "--pipeline", "src.baseline_t09") == 0
    d = pd.read_csv(tmp_path / "decisions.csv").set_index("case_id")
    assert d.loc["CASE-02", "decision"] == "GO"   # the failure mode the PoC fixes


def test_all_hold_baseline(tmp_path):
    assert _run(tmp_path, "--pipeline", "src.baseline_t09_allhold") == 0
    assert set(pd.read_csv(tmp_path / "decisions.csv").decision) == {"HOLD"}
