"""
Financial Planning API
======================
FastAPI server that fetches client records from Airtable and returns
structured client data for the Next.js dashboard.
"""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from stdio_utf8 import force_utf8_stdio  # noqa: E402

force_utf8_stdio()

import requests as http_requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from rsu_market import (  # noqa: E402
    get_prices_for_tickers,
    get_rsu_market_payload,
    refresh_rsu_market_payload,
)
from financial_plan_runner import (  # noqa: E402
    FinancialPlanDependencyError,
    run_financial_plan_for_client,
)

# Repo-root .env (same as agent/main.py)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Airtable config ──────────────────────────────────────────────────────────
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "appE5VYaHMHmorADN")
AIRTABLE_TABLE   = os.getenv("AIRTABLE_TABLE",   "Table 1")
AIRTABLE_TOKEN   = os.getenv("AIRTABLE_TOKEN",   "")
AIRTABLE_URL     = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE}"
AIRTABLE_HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_TOKEN}",
    "Content-Type":  "application/json",
}


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """UTF-8 stdio + optional langgraph presence check (Make plan)."""
    force_utf8_stdio()
    try:
        import langgraph  # noqa: F401

        print("[financial-plan] langgraph: OK (Make plan dependencies present)")
    except ModuleNotFoundError:
        print(
            "[financial-plan] WARNING: langgraph not installed. "
            "Run: pip install -r backend/requirements.txt"
        )
    yield


app = FastAPI(
    title="Financial Planning API",
    version="1.0.0",
    lifespan=_lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RsuRefreshBody(BaseModel):
    tickers: list[str] = []


class FinancialPlanRequest(BaseModel):
    record_id: str


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__},
    )


# ── Airtable helpers ─────────────────────────────────────────────────────────

def fetch_all_airtable_records() -> list[dict]:
    records = []
    params = {}
    while True:
        resp = http_requests.get(AIRTABLE_URL, headers=AIRTABLE_HEADERS, params=params)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Airtable error {resp.status_code}: {resp.text}",
            )
        body = resp.json()
        records.extend(body.get("records", []))
        offset = body.get("offset")
        if not offset:
            break
        params["offset"] = offset
    return records


def airtable_record_to_client_data(fields: dict) -> dict:
    def _f(key, default=0.0):
        val = fields.get(key)
        if val is None or val == "" or val == "NA":
            return default
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).replace("%", "").replace(",", "").strip()
        try:
            return float(s)
        except ValueError:
            return default

    def _i(key, default=0):
        return int(_f(key, default))

    def _s(key, default=""):
        val = fields.get(key)
        return str(val).strip() if val not in (None, "") else default

    def _bool(key):
        val = fields.get(key)
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("yes", "true", "1")

    def _rate(key, default=0.0):
        val = _f(key, None)
        if val is None:
            return default
        if val > 1:
            return round(val / 100, 6)
        return val

    def _date_iso(key, default=""):
        return _s(key, default)

    # ── 1. Personal / client block ───────────────────────────────────────────
    client_data_block = {
        "name":              _s("Name", "Unknown"),
        "pan":               _s("PAN"),
        "organization_name": _s("organization_name"),
        "date_of_birth":     _date_iso("dob"),
        "spouse_name":       _s("spouse_name"),
        "spouse_dob":        _date_iso("spouse_dob"),
        "if_any_kids":       _bool("is_kids"),
        "children":          [],
        "retirement_age":    _i("desired_retirement_age") or 60,
    }

    # ── 2. Children (up to 3) ────────────────────────────────────────────────
    children = []
    for n in range(1, 4):
        p    = f"child_{n}_"
        name = _s(f"{p}name")
        if not name:
            continue
        investments = []
        ssy_val     = _f(f"{p}ssy_current_amount") or _f(f"{p}ssy_current_value")
        ssy_start   = _s(f"{p}ssy_commencement_date") or _s(f"{p}ssy_commenecement_date")
        ssy_contrib = _f(f"{p}ssy_contribution")
        if ssy_val or ssy_contrib:
            investments.append({
                "type":                "SUKANYA SAMRIDDHI YOJANA",
                "commencement_date":   ssy_start,
                "annual_contribution": ssy_contrib,
                "current_value":       ssy_val,
            })
        children.append({
            "child_name":  name,
            "child_dob":   _date_iso(f"{p}dob"),
            "Gender":      _s(f"{p}gender"),
            "investments": investments,
        })

    client_data_block["children"]    = children
    client_data_block["if_any_kids"] = bool(children) or _bool("is_kids")

    # ── 3. Real estate ───────────────────────────────────────────────────────
    real_estate = []
    self_occ   = _f("self_occupied_property_value")
    rental_val = _f("rental_property_value")
    other_re   = _f("other_real_estate_investments_current_value")
    land       = _f("land_investments_current_value")
    total_re   = self_occ + other_re + land
    if total_re or rental_val:
        real_estate.append({"current_market_value": total_re, "rental_income": 0})
    if rental_val:
        real_estate.append({"current_market_value": rental_val, "rental_income": 0})
    if not real_estate:
        real_estate = [{"current_market_value": 0, "rental_income": 0}]

    # ── 4. EPF / PPF / NPS ──────────────────────────────────────────────────
    epf_list = []
    pf_val    = _f("pf_current_value")
    pf_contrib = _f("pf_employer_monthly_contribution")
    if pf_val or pf_contrib:
        epf_list.append({
            "current_value":                          pf_val,
            "employee_employer_contribution_monthly": pf_contrib,
            "interest_rate":                          0.085,
        })

    ppf_list    = []
    ppf_val     = _f("ppf_current_value")
    ppf_contrib = _f("ppf_contribution")
    if ppf_val or ppf_contrib:
        ppf_list.append({
            "current_value":       ppf_val,
            "annual_contribution": ppf_contrib,
            "interest_rate":       0.075,
        })

    nps_list      = []
    pension_name  = _s("pension_scheme_name")
    pension_val   = _f("pension_scheme_current_value")
    pension_contrib = _f("pension_scheme_contribution")
    if pension_name.upper() == "NPS" and (pension_val or pension_contrib):
        nps_list.append({
            "current_value":               pension_val,
            "monthly_contribution":        pension_contrib,
            "maturity_year":               _s("pension_scheme_maturity_date"),
            "expected_corpus_growth_rate": 0.10,
        })

    # ── 5. Fixed Deposits (up to 3) ──────────────────────────────────────────
    fd_list = []
    num_fds = _i("no_fd")
    for n in range(1, 4):
        if n > num_fds and num_fds > 0:
            break
        bank = _s(f"FD_{n}_bank_name")
        amt  = _f(f"FD_{n}_invested_amount")
        if bank or amt:
            fd_list.append({
                "name_of_bank":     bank or f"Bank_{n}",
                "principal_amount": amt,
                "interest_rate":    _rate(f"FD_{n}_rate_of_intrest"),
                "maturity_date":    _s(f"FD_{n}_maturity_date"),
            })

    # ── 6. Bonds ─────────────────────────────────────────────────────────────
    bond_list = []
    if _bool("is_bonds"):
        bond_amt = _f("bond_invested_amount")
        if bond_amt:
            bond_list.append({
                "bond_name":       _s("bond_name"),
                "invested_amount": bond_amt,
                "interest_rate":   _rate("bond_rate_interest"),
                "tenure_years":    _f("bond_tenure"),
            })

    # ── 7. Liabilities ───────────────────────────────────────────────────────
    liabilities = []
    num_home_loans = _i("no_home_loan")
    for n in range(1, 3):
        if n > num_home_loans and num_home_loans > 0:
            break
        emi = _f(f"home_loan_{n}_emi")
        bal = _f(f"home_loan_{n}_outstanding_amount")
        if emi or bal:
            liabilities.append({
                "type":                "Home loan",
                "outstanding_balance": bal,
                "interest_rate":       _rate(f"home_loan_{n}_rate_of_intrest"),
                "emi_amount":          emi,
                "is_under_penalty_period": False,
                "time_left_to_come_out_of_penalty_period(months)": 0,
            })

    if _bool("is_car_loan"):
        emi = _f("car_loan_emi")
        bal = _f("car_loan_outstanding_amount")
        if emi or bal:
            liabilities.append({
                "type":                "Car loan",
                "outstanding_balance": bal,
                "interest_rate":       _rate("car_loan_rate_intrest"),
                "emi_amount":          emi,
                "is_under_penalty_period": False,
                "time_left_to_come_out_of_penalty_period(months)": 0,
            })

    if _bool("is_personal_loan"):
        emi = _f("personal_loan_emi")
        bal = _f("personal_loan_oustanding_amount")
        if emi or bal:
            liabilities.append({
                "type":                "Personal loan",
                "outstanding_balance": bal,
                "interest_rate":       _rate("personal_loan_rate_intrest"),
                "emi_amount":          emi,
                "is_under_penalty_period": False,
                "time_left_to_come_out_of_penalty_period(months)": 0,
            })

    # ── 8. LIC policies (up to 3) ────────────────────────────────────────────
    lic_policies = []
    num_lic = _i("no_lic_policies")
    for n in range(1, 4):
        if n > num_lic and num_lic > 0:
            break
        p    = f"lic_policy_{n}_"
        name = _s(f"{p}name")
        if not name:
            continue
        lic_policies.append({
            "policy_name":          name,
            "commencement_date":    _s(f"{p}commencement_date"),
            "annual_premium":       _f(f"{p}premium") or _f(f"{p}premium_amount"),
            "premium_payment_term": _i(f"{p}ppt"),
            "policy_period":        _i(f"{p}policy_period"),
            "maturity_value":       _f(f"{p}maturity_value"),
            "linked_goal":          _s(f"{p}linked_goal_name"),
        })

    # ── 9. ULIPs (up to 2) ───────────────────────────────────────────────────
    ulip_list = []
    if _bool("is_ulips"):
        for n in range(1, 3):
            p    = f"ulip_policy_{n}_"
            name = _s(f"{p}name")
            if not name:
                continue
            ulip_list.append({
                "policy_name":          name,
                "commencement_date":    _s(f"{p}commenecement_date") or _s(f"{p}commencement_date"),
                "annual_premium":       _f(f"{p}premium"),
                "premium_payment_term": _i(f"{p}ppt"),
                "policy_term":          _i(f"{p}term"),
                "maturity_value":       _f(f"{p}maturity_value"),
                "maturity_year":        _i(f"{p}maturity_year"),
                "linked_goal":          _s(f"{p}linked_goal_name"),
            })

    # ── 10. Spouse investments ───────────────────────────────────────────────
    spouse_mf_val     = _f("spouse_investment_mutual_fund_value")
    spouse_eq_val     = _f("spouse_investment_direct_equity_value")
    spouse_vested     = _f("spouse_investment_vestd_esop")
    spouse_unvested   = _f("spouse_investment_unvested_esop")
    spouse_pf_val     = _f("spouse_investment_pf_current_value")
    spouse_pf_contrib = _f("spouse_investment_pf_contribution")
    spouse_fd_amt     = _f("spouse_investment_fd_bond_invested_amount")
    spouse_fd_rate    = _rate("spouse_investment_fd_bond_rate_intrest")
    spouse_fd_mat     = _s("spouse_investment_fd_bond_maturity_date")

    # ── 11. Investment pools ─────────────────────────────────────────────────
    mf_val       = _f("mutual_fund_current_value") + spouse_mf_val
    sip_amt      = _f("current_sip_going_on")
    mutual_funds = []
    if mf_val or sip_amt:
        mutual_funds.append({
            "current_value":          mf_val,
            "expected_annual_return": 0.12,
            "sip_amount":             sip_amt,
        })

    eq_val        = _f("direct_equity_current_value") + spouse_eq_val
    direct_equity = [{"portfolio_value": eq_val}]

    if spouse_pf_val or spouse_pf_contrib:
        epf_list.append({
            "current_value":                          spouse_pf_val,
            "employee_employer_contribution_monthly": spouse_pf_contrib,
            "interest_rate":                          0.085,
        })

    if spouse_fd_amt:
        fd_list.append({
            "name_of_bank":     "Spouse FD/Bond",
            "principal_amount": spouse_fd_amt,
            "interest_rate":    spouse_fd_rate,
            "maturity_date":    spouse_fd_mat,
        })

    esops = [{
        "vested_esops_value":   _f("vested_esop(s)_value") + spouse_vested,
        "unvested_esops_value": _f("unvested_esop(s)_value") + spouse_unvested,
    }]

    # ── RSU ──────────────────────────────────────────────────────────────────
    rsu_list = []
    if _s("Is_esop(s)").strip().upper() == "RSU(S)":
        no_companies = _i("No of companies")
        for i in range(1, no_companies + 1):
            duration         = _i(f"rsu_duration_{i}")
            vesting_schedule = []
            for j in range(1, duration + 1):
                vesting_schedule.append({
                    "year":      _s(f"rsu_{i}_year_{j}"),
                    "vesting":   _f(f"rsu_{i}_vesting_{j}"),
                    "no_shares": _i(f"rsu_{i}_no_shares_{j}"),
                })
            rsu_list.append({
                "company_name":     _s(f"rsu_company_{i}"),
                "ticker":           _s(f"rsu_ticker_{i}").upper(),
                "vesting_schedule": vesting_schedule,
            })

    # ── 12. Education planning ───────────────────────────────────────────────
    education_planning = []
    for idx, child in enumerate(children, start=1):
        p = f"child_{idx}_"
        education_planning.append({
            "name_of_kid":                   child["child_name"],
            "dob":                           child["child_dob"],
            "graduation_stream":             _s(f"{p}graduation_stream"),
            "graduation_destination":        _s(f"{p}graduation_destination"),
            "fund_allocated_for_graduation": 0,
            "post_graduation_stream":        _s(f"{p}post_graduation_stream"),
            "post_graduation_destination":   _s(f"{p}post_graduation_destination"),
            "scheme_for_education":          [],
        })

    # ── 13. Financial goals ──────────────────────────────────────────────────
    GOAL_COLUMN_MAP = {
        "home purchase - residential": ("capital_required_for_home_purchase", "target_year_home_purchase"),
        "real estate":                 ("capital_required_real_estate",       "target_year_real_estate"),
        "car":                         ("capital_required_car",               "target_year_car"),
        "vaccation":                   ("capital_required_vaccation",         "target_year_vaccation"),
        "other goal":                  ("capital_required_other_goal",        "target_year_other_goal"),
    }
    financial_goals  = []
    raw_goals_field  = fields.get("other_financial_goals", "")
    goal_labels      = raw_goals_field if isinstance(raw_goals_field, list) else [g.strip() for g in str(raw_goals_field).split(",") if g.strip()]
    other_goal_name  = _s("other_goal_name")
    for goal_label in goal_labels:
        cap_col, yr_col = GOAL_COLUMN_MAP.get(goal_label.lower(), (None, None))
        if cap_col:
            cap = _f(cap_col)
            yr  = _i(yr_col)
            if cap and yr:
                display_name = other_goal_name if goal_label.lower() == "other goal" and other_goal_name else goal_label
                financial_goals.append({
                    "goal_name":              display_name,
                    "capital_required_today": cap,
                    "target_year":            yr,
                })

    # ── 14. Life insurance ───────────────────────────────────────────────────
    life_insurance = []
    li_name     = _s("life_Insurance_company_name")
    li_coverage = _f("life_insurance_coverage_value")
    if li_name or li_coverage:
        life_insurance.append({"company_name": li_name, "coverage_value": li_coverage})

    # ── Assemble ─────────────────────────────────────────────────────────────
    investment_details = {
        "financial_summary": [{
            "monthly_salary":                                _f("current_salary"),
            "monthly_expenses_excl_emis":                    _f("current_monthly_expsenses"),
            "other_income(rental/interest/other)":           _f("other_income"),
            "lump_sum_available":                            _f("lumpsum_kept_aside"),
            "miscellaneous_kids_education_expenses_monthly": _f("miscellaneous_expenses"),
            "annual_vacation_expenses":                      _f("current_annual_vaction_expenses"),
            "emergency_fund_maintained":                     _f("emergency_fund"),
        }],
        "real_estate_investment": real_estate,
        "retirement_investments": {
            "epf":  epf_list,
            "ppf":  ppf_list,
            "nps":  nps_list,
            "ulip": ulip_list,
        },
        "bonds":             bond_list,
        "mutual_funds":      mutual_funds,
        "direct_equity":     direct_equity,
        "reits":             [{"current_value": _f("riet(s)_current_value")}],
        "pms_aif":           [{"current_value": _f("pms_aif_current_value")}],
        "esops":             esops,
        "rsu":               rsu_list,
        "fixed_deposits":    fd_list,
        "ulips":             ulip_list,
        "lic_policies":      lic_policies,
        "other_investments": [],
    }

    return {
        "client_data":        client_data_block,
        "investment_details": investment_details,
        "financial_goals":    financial_goals,
        "liabilities":        liabilities,
        "education_planning": education_planning,
        "life_insurance":     life_insurance,
    }


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/clients")
def list_clients():
    records = fetch_all_airtable_records()
    clients = [
        {"record_id": rec["id"], "name": rec.get("fields", {}).get("Name", f"Record {rec['id']}")}
        for rec in records
    ]
    return {"clients": clients}


@app.get("/clients/{record_id}")
def get_client_data(record_id: str):
    resp = http_requests.get(f"{AIRTABLE_URL}/{record_id}", headers=AIRTABLE_HEADERS)
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Client record not found in Airtable")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Airtable error: {resp.text}")
    fields = resp.json().get("fields", {})
    return {"record_id": record_id, "client_data": airtable_record_to_client_data(fields)}


@app.get("/rsu-market-data")
def get_rsu_market_data():
    """Return RSU market data (ticker prices + USD/INR) from the cached Parquet file."""
    try:
        return get_rsu_market_payload()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="RSU market data not available. Run refresh first.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/rsu-refresh")
def refresh_rsu_market_data(body: RsuRefreshBody | None = None):
    """Force-refresh RSU market data (USD/INR + prices for given tickers)."""
    tickers = body.tickers if body and body.tickers else None
    try:
        return refresh_rsu_market_payload(tickers=tickers)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"RSU refresh failed: {exc}"
        ) from exc


# Legacy paths (used by older Next.js routes)
@app.get("/rsu/market-data")
def rsu_market_data_legacy(ticker: list[str] = Query(default=[])):
    try:
        if ticker:
            return get_prices_for_tickers(ticker)
        return get_rsu_market_payload()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/rsu/market-data/refresh")
def rsu_market_data_refresh_legacy(
    force: bool = False,
    ticker: list[str] = Query(default=[]),
):
    try:
        return refresh_rsu_market_payload(
            tickers=ticker if ticker else None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/financial-plan/run")
def run_financial_plan(req: FinancialPlanRequest):
    """
    Run the integrated LangGraph financial planning workflow (Armstrong Financial_Planning)
    for the given Airtable record. Requires Azure OpenAI + Tavily in .env for LLM nodes.
    """
    import traceback

    resp = http_requests.get(f"{AIRTABLE_URL}/{req.record_id}", headers=AIRTABLE_HEADERS)
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Client record not found in Airtable")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Airtable error: {resp.text}")
    fields = resp.json().get("fields", {})
    client_payload = airtable_record_to_client_data(fields)
    try:
        return run_financial_plan_for_client(client_payload)
    except FinancialPlanDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OSError as exc:
        traceback.print_exc()
        filename = getattr(exc, "filename", None)
        detail = f"Financial plan I/O error: {exc}"
        if filename:
            detail += f" (file: {filename!r})"
        raise HTTPException(status_code=500, detail=detail) from exc
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Financial plan failed: {exc}"
        ) from exc


if __name__ == "__main__":
    port = int(os.getenv("FASTAPI_PORT", "8001"))
    print(f"Financial Planning API listening on http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
