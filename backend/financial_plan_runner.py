"""
Run the Armstrong LangGraph financial planning workflow from this repo.

Requires repo root on sys.path and cwd = repo root so Financial_Planning/* data paths resolve.
"""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from pathlib import Path

from stdio_utf8 import force_utf8_stdio

REPO_ROOT = Path(__file__).resolve().parent.parent


class FinancialPlanDependencyError(RuntimeError):
    """Raised when LangGraph / LangChain stack is not installed in the active Python env."""


def ensure_fp_runtime() -> None:
    force_utf8_stdio()
    os.chdir(str(REPO_ROOT))
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def build_ssy_summary_preview(oga: dict) -> list[dict]:
    """
    Build SSY Tracker rows for the plan review UI (matches Armstrong index.html ssy_summary).
    """
    if not isinstance(oga, dict):
        return []

    tracker = oga.get("ssy_tracker")
    if not isinstance(tracker, dict):
        tracker = {}

    total_fv_by_child: dict[str, float] = {}
    for g in oga.get("goals") or []:
        if not isinstance(g, dict):
            continue
        for f in g.get("funded_from") or []:
            if not isinstance(f, dict) or f.get("type") != "ssy_funds":
                continue
            source = str(f.get("source") or "")
            child = source.replace("SSY account of ", "").strip()
            if not child:
                continue
            tfv = f.get("total_ssy_fv")
            if tfv is not None:
                try:
                    total_fv_by_child[child] = max(
                        total_fv_by_child.get(child, 0.0), float(tfv)
                    )
                except (TypeError, ValueError):
                    pass

    rows: list[dict] = []
    for child_name, data in tracker.items():
        if not isinstance(data, dict):
            continue
        remaining = float(data.get("remaining_balance") or 0)
        maturity_year = data.get("maturity_year")
        total_fv = data.get("total_fv") or total_fv_by_child.get(child_name)
        locked = data.get("locked")
        if locked is None:
            locked = remaining > 0
        rows.append(
            {
                "child_name": child_name,
                "total_fv": total_fv,
                "total_withdrawn": data.get("total_withdrawn", 0),
                "remaining_balance": remaining,
                "maturity_year": maturity_year,
                "locked": bool(locked),
            }
        )
    return rows


def summarize_plan_state(state: dict) -> dict:
    """Compact view for API / UI (full state can be very large)."""
    cd = state.get("client_data") or {}
    inner = cd.get("client_data") or {}
    name = inner.get("name", "Client")
    fo = state.get("financial_overview") or {}
    ra = state.get("risk_appetite") or {}
    goals = state.get("sorted_goals")
    if isinstance(goals, list):
        goal_rows = [
            {
                "goal_name": g.get("goal_name"),
                "priority_score": g.get("priority_score"),
                "target_year": g.get("target_year"),
                "corpus_needed": g.get("corpus_needed"),
            }
            for g in goals[:25]
        ]
    else:
        goal_rows = []

    oga = state.get("optimal_goal_allocation") or {}
    oga_goals = oga.get("goals") if isinstance(oga, dict) else None
    schemes_fv = state.get("retirement_schemes_fv") or {}
    alloc_preview = []

    def _display_scheme_type(category: str) -> str:
        cat = str(category or "").strip()
        if not cat:
            return "Retirement Scheme"
        if cat.lower() in ("epf", "ppf", "nps", "ulip"):
            return cat.upper()
        return cat.replace("_", " ").title()

    def _retirement_scheme_rows() -> list[dict]:
        rows: list[dict] = []
        schemes_by_category = (
            schemes_fv.get("schemes", {}) if isinstance(schemes_fv, dict) else {}
        )
        category_totals = (
            schemes_fv.get("category_totals", {}) if isinstance(schemes_fv, dict) else {}
        )
        for category, schemes in schemes_by_category.items():
            scheme_type = _display_scheme_type(category)
            for scheme in schemes or []:
                if not isinstance(scheme, dict):
                    continue
                scheme_no = scheme.get("scheme_no")
                label = (
                    scheme_type
                    if scheme_no in (None, "")
                    else f"{scheme_type} {scheme_no}"
                )
                rows.append(
                    {
                        "type": scheme_type,
                        "label": label,
                        "amount": scheme.get("total_invested"),
                        "fv": scheme.get("future_value"),
                    }
                )
        if rows:
            return rows
        for category, total_fv in category_totals.items():
            if total_fv:
                rows.append(
                    {
                        "type": _display_scheme_type(category),
                        "label": _display_scheme_type(category),
                        "amount": None,
                        "fv": total_fv,
                    }
                )
        return rows

    def _extract_retirement_source_amount(entry: dict) -> float | None:
        if entry.get("source") == "future_values_retirement_investments":
            v = entry.get("amount")
            return float(v) if v is not None else None
        v = entry.get("future_values_retirement_investments")
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        return None

    def _normalize_funded_from(funded_from: list) -> list[dict]:
        """Match Armstrong api.py _funded() shape for the review UI."""
        out: list[dict] = []
        for f in funded_from:
            if not isinstance(f, dict):
                continue
            ft = f.get("type", "")
            if ft in ("sip_from_surplus", "sip_from_partial_surplus"):
                out.append(
                    {
                        "type": "SIP",
                        "monthly": f.get("monthly"),
                        "from_year": f.get("from_year"),
                        "to_year": f.get("to_year"),
                        "rate": f.get("rate"),
                        "fv": f.get("fv_contribution"),
                    }
                )
            elif ft == "freed_sip":
                out.append(
                    {
                        "type": "Freed EMI",
                        "monthly": f.get("monthly"),
                        "from_year": f.get("from_year"),
                        "to_year": f.get("to_year"),
                        "rate": f.get("rate"),
                        "fv": f.get("fv_contribution"),
                    }
                )
            elif ft in ("lumpsum_from_liquid", "lumpsum_from_liquid_partial"):
                out.append(
                    {
                        "type": "Lumpsum",
                        "amount": f.get("principal_used_today", f.get("amount_used")),
                        "from_year": f.get("from_year"),
                        "to_year": f.get("to_year"),
                        "rate": f.get("rate"),
                        "fv": f.get("fv_contribution"),
                    }
                )
            elif ft == "ssy_funds":
                out.append(
                    {
                        "type": "SSY",
                        "amount": f.get("amount_used"),
                        "fv": f.get("fv_contribution"),
                    }
                )
            elif ft == "esop_funds":
                out.append(
                    {
                        "type": "ESOP",
                        "amount": f.get("amount_used"),
                        "fv": f.get("fv_contribution"),
                    }
                )
            elif ft == "rsu_funds":
                out.append(
                    {
                        "type": "rsu_funds",
                        "source": f.get("source"),
                        "ticker": f.get("ticker"),
                        "amount_used": f.get("amount_used"),
                    }
                )
        return out

    if isinstance(oga_goals, list):
        for g in oga_goals[:20]:
            raw_note = g.get("note")
            if isinstance(raw_note, list):
                notes_out = [str(x)[:800] for x in raw_note[:8]]
            elif raw_note:
                notes_out = [str(raw_note)[:800]]
            else:
                notes_out = []
            raw_funded = g.get("funded_from") if isinstance(g.get("funded_from"), list) else []
            funded_preview = _normalize_funded_from(raw_funded)

            goal_name = str(g.get("goal_name") or "")
            if goal_name.lower() == "retirement":
                sourced = g.get("sourced_from") if isinstance(g.get("sourced_from"), list) else []
                if not sourced:
                    sourced = [
                        item
                        for item in raw_funded
                        if isinstance(item, dict)
                        and (
                            "future_values_retirement_investments" in item
                            or item.get("source")
                            == "future_values_retirement_investments"
                        )
                    ]
                ret_amount = next(
                    (
                        amt
                        for amt in (
                            _extract_retirement_source_amount(dict(item))
                            for item in sourced
                            if isinstance(item, dict)
                        )
                        if amt is not None
                    ),
                    None,
                )
                if ret_amount is None and isinstance(schemes_fv, dict):
                    ret_amount = schemes_fv.get("grand_total")
                if ret_amount is not None:
                    funded_preview.append(
                        {
                            "type": "Retirement Schemes",
                            "total_fv": ret_amount,
                            "breakdown": _retirement_scheme_rows(),
                        }
                    )

            alloc_preview.append(
                {
                    "goal_name": g.get("goal_name"),
                    "corpus_needed": g.get("corpus_needed"),
                    "corpus_gap": g.get("corpus_gap"),
                    "target_corpus": g.get("target_corpus"),
                    "target_year": g.get("target_year"),
                    "filter": g.get("filter"),
                    "notes": notes_out,
                    "funded_from_preview": funded_preview,
                }
            )

    def _last_num(val):
        if val is None:
            return None
        if isinstance(val, list) and val:
            try:
                return float(val[-1])
            except (TypeError, ValueError):
                return val[-1]
        return val

    oga_for_ssy = state.get("optimal_goal_allocation") or {}
    ssy_summary_preview = build_ssy_summary_preview(
        oga_for_ssy if isinstance(oga_for_ssy, dict) else {}
    )

    term_insurance_requirement = None
    term = state.get("term_insurance_summary") or {}
    if term:
        def _num(v):
            if v is None:
                return 0
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return 0

        pv = _num(term.get("pv_of_expenses", 0))
        edu = _num(term.get("kids_education_cost", 0))
        liab = _num(term.get("current_liabilities", 0))
        cover = _num(term.get("existing_cover", 0))
        liquid = _num(term.get("liquidable_assets", 0))
        total = _num(term.get("total_term_required", 0))

        term_insurance_requirement = {
            "section": "Term Insurance Requirement",
            "total_cover_required": total,
            "breakdown": {
                "income_replacement_corpus": pv,
                "kids_education_cost": edu,
                "outstanding_liabilities": liab,
                "less_existing_cover": -cover,
                "less_liquid_assets": -liquid,
            },
            "note": (
                f"Client needs a total term cover of "
                f"₹{total:,}. "
                f"This accounts for income replacement (₹{pv:,}), "
                f"children's education (₹{edu:,}), "
                f"outstanding liabilities (₹{liab:,}), "
                f"less existing cover (₹{cover:,}) "
                f"and liquid assets (₹{liquid:,})."
            ),
        }

    return {
        "client_name": name,
        "monthly_surplus": state.get("monthly_surplus"),
        "risk_appetite": ra,
        "financial_overview_keys": list(fo.keys()) if isinstance(fo, dict) else [],
        "liquidity_ratio": fo.get("liquidity_ratio") if isinstance(fo, dict) else None,
        "liquidity_flag": fo.get("liquidity_flag") if isinstance(fo, dict) else None,
        "flexibility": fo.get("flexibility") if isinstance(fo, dict) else None,
        "spending_behavior": fo.get("spending_behavior") if isinstance(fo, dict) else None,
        "ending_liquid_pool": _last_num(oga.get("ending_liquid_pool")) if isinstance(oga, dict) else None,
        "ending_monthly_surplus": _last_num(oga.get("ending_monthly_surplus")) if isinstance(oga, dict) else None,
        "sorted_goals_preview": goal_rows,
        "goal_allocation_preview": alloc_preview,
        "loans_exist": state.get("loans_exist"),
        "final_unused_monthly_surplus": state.get("final_unused_monthly_surplus"),
        "retirement_goal_preview": (state.get("retirement_goal") or [])[:2]
        if isinstance(state.get("retirement_goal"), list)
        else state.get("retirement_goal"),
        "ssy_summary_preview": ssy_summary_preview,
        "term_insurance_requirement": term_insurance_requirement,
    }


def _load_workflow_runner():
    try:
        from Financial_Planning.Workflow.workflow import run_financial_plan_workflow

        return run_financial_plan_workflow
    except ModuleNotFoundError as e:
        name = getattr(e, "name", None) or str(e)
        raise FinancialPlanDependencyError(
            "Missing Python package(s) for Make plan. Use the same venv as the FastAPI server and run: "
            "pip install -r backend/requirements.txt "
            f"(import failed for: {name})."
        ) from e


def run_financial_plan_for_client(client_payload: dict) -> dict:
    """
    client_payload: same shape as Armstrong `client_data` (client_data + investment_details + goals + ...).
    """
    import traceback

    ensure_fp_runtime()
    run_financial_plan_workflow = _load_workflow_runner()

    payload = deepcopy(client_payload)
    try:
        raw = run_financial_plan_workflow(payload)
        summary = summarize_plan_state(raw)
    except OSError as exc:
        print("=" * 60, file=sys.stderr)
        print(f"OSError in make plan: {exc}", file=sys.stderr)
        print(f"Error code: {exc.errno}", file=sys.stderr)
        print(f"Filename involved: {getattr(exc, 'filename', None)!r}", file=sys.stderr)
        traceback.print_exc()
        print("=" * 60, file=sys.stderr)
        raise
    return {
        "ok": True,
        "summary": summary,
    }
