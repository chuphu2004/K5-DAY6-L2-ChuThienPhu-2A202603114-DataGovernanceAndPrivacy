"""T09 Multi-Market Privacy Decision Gate — offline policy engine.

Lab contract = 5 automated steps, run by `python -m src.main ...`:
    01 load      12 case JSONs + versioned policy YAML (manifest.csv hash check)
    02 process   evaluate every rule for the case's market -> GO / HOLD / REWORK + reason codes + sources
    03 rank      review queue: all cases, HOLD first (legal owner signs off on every case)
    04 review    reviewer decisions from out/.../review_queue_reviewed.csv -> overrides + audit log
    05 decide    run-level Decision + out/decisions.csv + out/checklist.csv (audit checklist)

Rules live in configs/policy/t09_policy.yaml (params.policy_file), never in this code.
Not legal advice: every decision is a recommendation for DPO/legal sign-off.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd
import yaml

from .common.context import RunContext
from .common.contact_sheet import render_contact_sheet
from .common.decision import Decision, canonical_status, write_decision
from .common.manifest import verify_manifest
from .common.review import load_review_decisions, make_review_queue, write_review_queue
from .metrics.tracks import get_track

SEVERITY = {"GO": 0, "REWORK": 1, "HOLD": 2}   # precedence HOLD > REWORK > GO


# ---------------------------------------------------------------- rule DSL
class _Node(dict):
    """Case JSON with attribute access; missing keys read as None (so `not lia_done` is True when absent)."""

    def __missing__(self, key):
        return None

    def __getattr__(self, key):
        v = self.get(key)
        return _Node(v) if isinstance(v, dict) else v


_ALLOWED = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.Compare, ast.Eq, ast.NotEq,
            ast.In, ast.NotIn, ast.Is, ast.IsNot, ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Name, ast.Load,
            ast.Attribute, ast.Constant, ast.List, ast.Tuple)


def compile_rule(expr: str):
    """Parse a `when` expression; only comparisons, boolean ops, dotted names and literals are allowed."""
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED) or (isinstance(node, (ast.Name, ast.Attribute)) and
                                              (getattr(node, "id", None) or node.attr).startswith("_")):
            raise ValueError(f"rule expression not allowed ({type(node).__name__}): {expr!r}")
    return compile(tree, "<rule>", "eval")


def eval_rule(code, case: dict) -> bool:
    env = _Node({k: (_Node(v) if isinstance(v, dict) else v) for k, v in case.items()})
    env.update(null=None, true=True, false=False)
    # eval is safe here: compile_rule whitelists the AST (no calls, no dunder access), builtins are empty,
    # and the rule file is versioned repo config, not user input.
    return bool(eval(code, {"__builtins__": {}}, env))


def load_policy(path: Path) -> dict:
    policy = yaml.safe_load(path.read_text(encoding="utf-8"))
    for r in policy["rules"]:
        missing = [k for k in ("id", "markets", "when", "decision", "reason_code", "source") if k not in r]
        if missing:
            raise ValueError(f"rule {r.get('id', '?')} missing {missing} (every rule needs a source)")
        canonical_status(r["decision"])
        r["_code"] = compile_rule(r["when"])
    return policy


def evaluate_case(case: dict, policy: dict, as_of: str) -> dict:
    market = case.get("market")
    fired, upcoming, checklist = [], [], []
    if market not in policy.get("covered_markets", []):
        fired.append({"id": "R-MARKET", "decision": "HOLD", "reason_code": "AMBIGUOUS_NEEDS_LEGAL",
                      "source": {"doc": "Internal policy", "ref": f"market {market!r} not covered"}, "needs_legal_review": True})
    for r in policy["rules"]:
        if "*" not in r["markets"] and market not in r["markets"]:
            continue
        hit = eval_rule(r["_code"], case)
        future = str(r.get("effective_date", "")) > as_of
        status = "upcoming" if (hit and future) else ("fail" if hit else "pass")
        checklist.append({"case_id": case["case_id"], "market": market, "rule_id": r["id"], "result": status,
                          "decision_if_fail": r["decision"], "reason_code": r["reason_code"],
                          "source": f"{r['source'].get('doc', '')} — {r['source'].get('ref', '')}",
                          "effective_date": str(r.get("effective_date", "")),
                          "needs_legal_review": bool(r.get("needs_legal_review", False))})
        if status == "fail":
            fired.append(r)
        elif status == "upcoming":
            upcoming.append(f"{r['id']}:{r['reason_code']}@{r['effective_date']}")
    decision = max((r["decision"] for r in fired), key=SEVERITY.get, default="GO")
    codes = list(dict.fromkeys(r["reason_code"] for r in fired))
    return {
        "case_id": case["case_id"], "market": market, "decision": decision, "reason_codes": ";".join(codes),
        "rule_ids": ";".join(r["id"] for r in fired),
        "sources": " | ".join(f"{r['id']}: {r['source'].get('doc', '')} {r['source'].get('ref', '')}".strip() for r in fired),
        "upcoming": ";".join(upcoming),
        "needs_legal_review": any(r.get("needs_legal_review") for r in fired),
        "ambiguity_notes": case.get("ambiguity_notes", ""),
        "facts": _facts(case),
        "_checklist": checklist,
    }


def _facts(c: dict) -> str:
    """One-line evidence summary shown to the legal reviewer."""
    con, st, tr = c.get("consent", {}), c.get("storage", {}), c.get("transfer", {})
    return (f"data={','.join(c.get('data_types', []))} · basis={c.get('lawful_basis')} · "
            f"consent(obtained={con.get('obtained')}, granular={con.get('granular')}, withdrawable={con.get('withdrawable')}, record={con.get('record_available')}) · "
            f"notice={c.get('notice_given')} · storage={st.get('location')}, raw={st.get('raw_retained')}, enc={st.get('encryption_at_rest')} · "
            f"transfer={'→ ' + str(tr.get('destination')) + ' via ' + str(tr.get('mechanism')) + ', TIA=' + str(tr.get('transfer_impact_assessment')) if tr.get('cross_border') else 'none'} · "
            f"retention={c.get('retention_days')}d · DPIA={c.get('dpia_done')} · minors={c.get('minors_possible')} · "
            f"LIA={c.get('lia_done', c.get('li_assessment_done'))}")


def _resolve(ctx: RunContext, p: str) -> Path:
    path = Path(p)
    return path if path.exists() else ctx.input_dir / p


# ---------------------------------------------------------------- 01 load
def load(ctx: RunContext) -> dict:
    manifest = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest) if manifest.exists() else [{"problem": "no_manifest"}]
    if problems:
        ctx.audit.log(actor="pipeline", action="provenance_problems", item_id=str(manifest), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")
    if ctx.track != "t09":
        raise NotImplementedError(f"src/pipeline.py implements t09 only (got {ctx.track}). See docs/tracks/{ctx.track.upper()}.md")
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ctx.input_dir / "cases").glob("CASE-*.json"))]
    if not cases:
        raise FileNotFoundError(f"no cases/CASE-*.json under {ctx.input_dir}")
    policy_path = _resolve(ctx, ctx.param("policy_file", "rules/policy_example.yaml"))
    policy = load_policy(policy_path)
    ctx.stats.update(policy_file=str(policy_path), policy_version=policy.get("policy_version"), n_rules=len(policy["rules"]))
    return {"cases": cases, "policy": policy}


# ---------------------------------------------------------------- 02 process
def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    as_of = str(ctx.param("as_of_date", "2026-11-14"))
    rows = [evaluate_case(c, data["policy"], as_of) for c in data["cases"]]
    pd.DataFrame([x for r in rows for x in r.pop("_checklist")]).to_csv(ctx.out("checklist.csv"), index=False)
    df = pd.DataFrame(rows)
    df["auto_decision"] = df["decision"]
    df["score"] = df.decision.map(SEVERITY) + df.needs_legal_review.astype(int) * 0.5 + df.reason_codes.str.count(";") * 0.01
    df["reason"] = df.reason_codes.where(df.reason_codes != "", "no rule fired")
    for r in df.itertuples(index=False):
        ctx.audit.log(actor="policy_engine", action="auto_decision", item_id=r.case_id, after=r.decision,
                      reason=r.reason_codes, rule_ids=r.rule_ids, policy_version=data["policy"].get("policy_version"))
    return df


# ---------------------------------------------------------------- 03 rank
def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    """Every case goes to the legal owner (budget defaults to all cases), HOLD + needs_legal_review first."""
    budget = int(ctx.param("budget", len(scored)))
    q = make_review_queue(scored, id_col="case_id", score_col="score", budget=budget, reason_col="reason",
                          action_col="decision", slice_col="market")
    write_review_queue(q, ctx.out("review_queue.csv"))
    # extra columns are display-only; the sheet's Export CSV still writes the standard review columns
    show = q.merge(scored[["case_id", "facts", "rule_ids", "sources", "upcoming", "ambiguity_notes"]],
                   left_on="item_id", right_on="case_id", how="left")
    render_contact_sheet(show, ctx.out("contact_sheet.html"), image_col=None, title="T09 privacy gate — legal review",
                         fields=("rank", "item_id", "slice", "suggested_action", "reason", "facts", "rule_ids",
                                 "sources", "upcoming", "ambiguity_notes"))
    return q


# ---------------------------------------------------------------- 04 review
def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    """approve = keep auto decision; edit/reject + override_value (GO/HOLD/REWORK) = change it; escalate = HOLD."""
    final = scored.copy()
    final["reviewer"] = ""
    final["review_note"] = ""
    reviewed_path = ctx.output_dir / "review_queue_reviewed.csv"
    if not reviewed_path.exists():
        return final
    reviewed = load_review_decisions(reviewed_path)
    ctx.stats["n_reviewed"] = len(reviewed)
    for r in reviewed.itertuples(index=False):
        mask = final.case_id == r.item_id
        if not mask.any():
            raise ValueError(f"reviewed item {r.item_id!r} is not a case in this run")
        before = final.loc[mask, "decision"].iloc[0]
        after = before
        if r.reviewer_decision in {"edit", "reject"}:
            if not r.override_value.strip():
                raise ValueError(f"{r.item_id}: {r.reviewer_decision} needs override_value GO/HOLD/REWORK")
            after = canonical_status(r.override_value)
        elif r.reviewer_decision == "escalate":
            after = "HOLD"
        final.loc[mask, ["decision", "reviewer", "review_note"]] = [after, r.reviewer, r.review_note]
        ctx.audit.log(actor=r.reviewer, action=f"review:{r.reviewer_decision}", item_id=r.item_id,
                      before=before, after=after, reason=r.review_note)
    return final


# ---------------------------------------------------------------- 05 decide
def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    counts = final.decision.value_counts().to_dict()
    worst = max(final.decision, key=SEVERITY.get)
    pending = int((final.reviewer == "").sum())
    return Decision(status=worst, reason_code=f"GATE_{worst}" if worst != "GO" else "ALL_CASES_CLEAR",
                    reason=f"{counts.get('HOLD', 0)} HOLD, {counts.get('REWORK', 0)} REWORK, {counts.get('GO', 0)} GO; "
                           f"{pending} case(s) still awaiting legal sign-off",
                    owner=ctx.config.get("owner", "TODO-owner"), scope=ctx.track,
                    evidence=[str(ctx.out("decisions.csv")), str(ctx.out("checklist.csv")), str(ctx.audit.path)],
                    metrics={"counts": counts, "pending_review": pending, "policy_version": ctx.stats.get("policy_version")})


def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)
    final[spec.pred_columns + [c for c in final.columns if c not in spec.pred_columns]].to_csv(ctx.out(spec.pred_file), index=False)
    write_decision(decide(ctx, final), ctx.out("decision.json"), ctx.out("decision_log.csv"))
