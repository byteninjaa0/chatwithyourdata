"""
Retirement Planning Nodes - Corpus & Goal Analysis

What this file does:
This script handles all retirement-related calculations including corpus requirements,
investment projections, and goal gap analysis for retirement planning.

What this file contains and processes:
- calculate_retirement_corpus: Calculates required retirement corpus using both standard (flat expenses) and segmented (phased lifestyle) methods
- calculate_all_retirement_investments: Computes future values of EPF, PPF, NPS, ULIP schemes with category totals and grand total
- retirement_goal: Evaluates retirement corpus gap by comparing required vs estimated corpus and creates standardized retirement goal
"""

# retirement nodes:  calculate_retirement_corpus, calculate_all_retirement_investments, retirement_goal
from Financial_Planning.Models.client_data_state import ClientState
from datetime import datetime, date
from collections import defaultdict
from Financial_Planning.Utilities.utility_functions import (calculate_future_value, calculate_present_value_annuity, epf_future_value, 
                                                            ppf_future_value, nps_future_value, calculate_investment_details)
from Financial_Planning.RSU.constants import get_rsu_growth_rate

# ── Post-retirement yield rates (NOMINAL) ───────────────────────────────────
# Used by calculate_retirement_annuity to convert a retirement-year corpus into
# perpetual annual income. These are NOMINAL rates, deliberately matched to the
# nominal (future-value) basis of both the corpus and desired_monthly_annuity.
# Do NOT substitute the plan's `real_return_rate` (0.04) here — that is a real
# rate and belongs only with a today's-money target.
POST_RETIREMENT_YIELD_RATES = {
    "epf":        0.085,  # assumes corpus stays in EPF-like debt post-retirement
    "ppf":        0.085,
    "nps":        0.07,   # blended: ~40% mandatory annuity (~6%) + invested remainder
    "sip":        0.10,   # SIP / freed-EMI / lumpsum are MF-invested
    "freed_sip":  0.10,
    "lumpsum":    0.10,
    "mutual_funds": 0.10,
}

# Breakdown buckets deliberately excluded from annuity income:
#   real_estate — its income is already counted as rental/other income (source 3);
#                 yielding the capital value too would double-count the same asset.
ANNUITY_EXCLUDED_BUCKETS = {"real_estate"}


def _parse_rate_string(rate_str, default: float = 0.065) -> float:
    if isinstance(rate_str, (int, float)):
        return float(rate_str)
    if not rate_str or rate_str == "-":
        return default
    try:
        return float(str(rate_str).replace("%", "").strip()) / 100
    except (TypeError, ValueError):
        return default

def calculate_retirement_corpus(state: ClientState):
    """
    Calculates the required retirement corpus using two methods:
    1. Standard Method: Flat expenses throughout retirement
    2. Segmented Cash Flow Method: Lifestyle-based phases with varying expenses
    
    Args:
        client_data (dict): Client's financial and personal data
        retirement_age (int): Age at which client plans to retire (default: 60)
        life_expectancy (int): Expected life expectancy (default: 85)
        inflation_rate (float): Annual inflation rate (default: 6%)
    
    Returns:
        dict: Detailed retirement corpus calculation with both methods
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: calculate_retirement_corpus \n")
    print("Calculating retirement corpus... \n")
    client_data=state['client_data']
    life_expectancy=85                    # pre-defined
    inflation_rate=0.06                   # pre-defined 
    real_return_rate = 0.04                # pre-defined

    # Extract client information
    client_dob = datetime.strptime(client_data['client_data']['date_of_birth'], '%Y-%m-%d').date() 
    current_age = date.today().year - client_dob.year
    monthly_expenses = client_data['investment_details']['financial_summary'][0]['monthly_expenses_excl_emis']
    annual_expenses = monthly_expenses*12 #+ (client_data['investment_details']['financial_summary'][0]["miscellaneous_kids_education_expenses_monthly"])*12 + client_data['investment_details']['financial_summary'][0]["annual_vacation_expenses"]
    retirement_age=client_data['client_data']['retirement_age']
    # Calculate years to retirement and retirement duration
    years_to_retirement = retirement_age - current_age
    retirement_duration = life_expectancy - retirement_age
    
    # Future annual expenses at retirement (adjusted for inflation)
    future_annual_expenses = calculate_future_value(annual_expenses, inflation_rate, years_to_retirement)
    
    retirement_plan = {
        "client_info": {
            "current_age": current_age,
            "retirement_age": retirement_age,
            "life_expectancy": life_expectancy,
            "years_to_retirement": years_to_retirement,
            "retirement_duration": retirement_duration,
            "current_monthly_expenses": monthly_expenses,
            "current_annual_expenses": annual_expenses,
            "future_annual_expenses_at_retirement": round(future_annual_expenses, 2)
        }
    }
    
    standard_corpus = calculate_present_value_annuity(
        future_annual_expenses, 
        real_return_rate, 
        retirement_duration
    )
    
    retirement_plan["standard_method"] = {
        "annual_expenses_throughout_retirement": round(future_annual_expenses, 2),
        "real_return_rate_assumed": real_return_rate,
        "required_corpus": round(standard_corpus, 2)
    }
    
    phases = [
        {
            "name": "Early Retirement",
            "age_range": "55-65",
            "start_age": retirement_age,
            "end_age": 65,
            "expense_multiplier": 1.1,  # 10% higher
            "description": "Active lifestyle, travel"
        },
        {
            "name": "Middle Retirement", 
            "age_range": "65-75",
            "start_age": 65,
            "end_age": 75,
            "expense_multiplier": 1.0,  # Normal expenses
            "description": "Baseline expenses"
        },
        {
            "name": "Late Retirement",
            "age_range": "75-85", 
            "start_age": 75,
            "end_age": life_expectancy,
            "expense_multiplier": 1.2,  # 20% higher
            "description": "Healthcare, support needs"
        }
    ]
    
    segmented_phases = [] 
    total_segmented_corpus = 0 
    
    for phase in phases:

        phase_start = max(phase['start_age'], retirement_age)
        phase_end = phase["end_age"]
        phase_duration = phase_end - phase_start
        
        if phase_duration <= 0:
            continue
            
        # Calculate expenses for this phase
        phase_annual_expenses = future_annual_expenses * phase["expense_multiplier"]
        
        # Calculate years from retirement to start of this phase
        years_to_phase_start = phase_start - retirement_age
        
        # Discount the required corpus back to retirement age
        if years_to_phase_start > 0:
            # Phase starts later, so discount the annuity back
            phase_corpus_at_phase_start = calculate_present_value_annuity(
                phase_annual_expenses, real_return_rate, phase_duration
            )
            phase_corpus_at_retirement = phase_corpus_at_phase_start / ((1 + real_return_rate) ** years_to_phase_start)
        else:
            # Phase starts immediately at retirement
            phase_corpus_at_retirement = calculate_present_value_annuity(
                phase_annual_expenses, real_return_rate, phase_duration
            )
        
        phase_info = {
            "phase_name": phase["name"],
            "age_range": f"{phase_start}-{phase_end}",
            "duration_years": phase_duration,
            "expense_multiplier": phase["expense_multiplier"],
            "annual_expenses": round(phase_annual_expenses, 2),
            "corpus_required": round(phase_corpus_at_retirement, 2),
            "description": phase["description"]
        }
        
        segmented_phases.append(phase_info)
        total_segmented_corpus += phase_corpus_at_retirement
    
    retirement_plan["segmented_method"] = {
        "phases": segmented_phases,
        "total_required_corpus": round(total_segmented_corpus, 2)
    }
    
    difference = total_segmented_corpus - standard_corpus
    percentage_diff = (difference / standard_corpus) * 100
    
    retirement_plan["comparison"] = {
        "standard_corpus": round(standard_corpus, 2),
        "segmented_corpus": round(total_segmented_corpus, 2),
        "difference": round(difference, 2),
        "percentage_difference": round(percentage_diff, 1)
    }
    
    # Recommended corpus (higher of the two)
    recommended_corpus = max(standard_corpus, total_segmented_corpus)
    retirement_plan["recommendation"] = {
        "recommended_corpus": round(recommended_corpus, 2),
        "method_used": "Segmented Method" if total_segmented_corpus > standard_corpus else "Standard Method",
        "rationale": "Taking the higher estimate to ensure adequate retirement funding"
    }
    
    print(f"retirement plan: {retirement_plan}\n")
    print("--------------------------"*6)
    return {'required_retirement_corpus': retirement_plan}


def calculate_all_retirement_investments(state: ClientState):
    """
    Computes future values of all retirement investment schemes, returning 
    per-scheme details, per-category totals, and an overall grand total.

    Args:
        state (ClientState): Contains client data with:
            - client_data.client_age (int)
            - investment_details.retirement_investments (dict) where keys are 
              categories ("ulip", "epf", "ppf", "nps") and values are lists of schemes.
              Each scheme includes fields like start date, contribution amounts, 
              rates, term/maturity, etc. (varies by category).

    Returns:
        dict: {
            "retirement_schemes_fv": {
                "schemes": {category: [ {scheme_no, future_value, total_invested}, ... ]},
                "category_totals": {category: float},
                "grand_total": float
            }
        }

    Purpose:
        Projects the corpus for each scheme until maturity/retirement, aggregates 
        by category, and produces a consolidated total.
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: calculate_all_retirement_investments")
    print("Calculating future value of retirement funds... \n")
    retirement_investments=state['client_data']['investment_details']['retirement_investments']
    current_age = state['client_data']['client_data']['client_age'] 
    retirement_age=state['client_data']['client_data']['retirement_age']
    today=datetime.today() 
    
    results          = defaultdict(list)   # per-scheme data
    category_totals  = {}                  # per-category sum
    grand_total      = 0.0
    
    for category, scheme_list in retirement_investments.items():
        cat_total = 0.0 

        for i, sc in enumerate(scheme_list, start=1):
            # ---------- ULIP (UPDATED field names) ----------
            if category.lower() == "ulip":
                pass
            #    # Create end date from final year of premium + term
            #    start_date = sc["commencement_date_of_ulip_policy_1"]
            #    ppt = sc['ppt']
            #    term = sc["term"]
            #    maturity_amount = sc["maturity_value"]
                
                

            # ---------- EPF (field names remain same) ----------
            elif category.lower() == "epf" and sc["current_value"]!=0 and sc["employee_employer_contribution_monthly"]!=0:
                # EPF doesn't have maturity_year in new structure, use retirement age
                years_left = retirement_age - current_age 
                fv = epf_future_value(
                        sc["current_value"],
                        sc["employee_employer_contribution_monthly"],
                        sc["interest_rate"],
                        years_left)   
                invested = sc["current_value"] + \
                           sc["employee_employer_contribution_monthly"] * 12 * max(years_left, 0)

            # ---------- PPF (field names remain same) ----------
            elif category.lower() == "ppf" and sc["current_value"]!=0 and sc["annual_contribution"]!=0:
                # PPF doesn't have lock_in_end_year, assume 15-year lock-in from current year 
                years_left = retirement_age - current_age  # Standard PPF lock-in period is 15 years but here we consider the left years are upto the retirement age.
                fv = ppf_future_value(
                        sc["current_value"],
                        sc["annual_contribution"],
                        sc["interest_rate"],
                        years_left) 
                invested = sc["current_value"]+sc["annual_contribution"]*years_left

            # ---------- NPS (UPDATED field names) ----------
            elif category.lower() == "nps" and sc["current_value"]!=0 and sc["monthly_contribution"]!=0: 
                # Calculate months left until maturity year 
                months_left = max((sc["maturity_year"] - today.year) * 12, 0)
                fv = nps_future_value( 
                        sc["current_value"],
                        sc["monthly_contribution"],
                        sc["expected_corpus_growth_rate"],
                        months_left) 
                invested = sc["current_value"] + sc["monthly_contribution"] * months_left

            elif category.lower()=='other' and sc['monthly_investment']>0:
                category=sc['scheme_name'] 
                invested, fv=calculate_investment_details(sc)

            else: 
                # Skip unknown categories gracefully
                continue

            results[category].append({
                "scheme_no"     : i,
                "future_value"  : fv,
                "total_invested": round(invested, 2)
            })
            cat_total += fv 

        if cat_total:
            category_totals[category] = round(cat_total, 2)
            grand_total += cat_total

    retirement_schemes_fv={
        "schemes"         : dict(results),
        "category_totals" : category_totals,
        "grand_total"     : round(grand_total, 2)
    }
    
    print(f"retirement schemes: {retirement_schemes_fv}\n")
    print("--------------------------"*6)
    return {"retirement_schemes_fv": retirement_schemes_fv}

def retirement_goal(state: ClientState):
    """
    Evaluates the retirement goal against the estimated corpus and consolidates it 
    with other education and financial goals.

    Args:
        state (ClientState): Contains client data and prior calculations with:
            - client_data.client_data.client_age (int)
            - client_data.client_data.retirement_age (int)
            - required_retirement_corpus.recommendation.recommended_corpus (float)
            - retirement_schemes_fv.grand_total (float)
            - education_planning_summary (list[dict]): Goals with name, type, target_year, final_gap
            - financial_goals (list[dict]): Goals with goal_name, target_year, goal_gap

    Returns:
        dict: {
            "goals": [
                {
                    "goal_name": str,
                    "corpus_needed": float,
                    "corpus_gap": float,
                    "target_year": int,
                    "funded_from": list,
                    "surplus": float (only for retirement goal)
                },
                ...
            ]
        }

    Purpose:
        - Compares required vs. estimated retirement corpus to compute gaps or surplus.
        - Builds a unified list of all goals (retirement, education, financial).
        - Standardizes each goal with common fields for downstream planning.
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: retirement_goal \n")
    print("Define a retirement goal...")
    client_data3=state['client_data']
    required_retirement_corpus= state['required_retirement_corpus']['recommendation']['recommended_corpus']
    estimated_retirement_corpus = state['retirement_schemes_fv']['grand_total']
    retirement_age = state['client_data']['client_data']['retirement_age']
    current_date=date.today()
    current_year=current_date.year
    years_to_retire = retirement_age - client_data3['client_data']['client_age']

    if required_retirement_corpus>estimated_retirement_corpus:
        result={} 
        result['goal_name']="retirement"
        result['target_corpus']=required_retirement_corpus 
        result['corpus_needed']=required_retirement_corpus-estimated_retirement_corpus
        result['corpus_gap']=required_retirement_corpus-estimated_retirement_corpus
        result['target_year']= current_year + years_to_retire
        if estimated_retirement_corpus>0:
            result['funded_from']=[{'future_values_retirement_investments':estimated_retirement_corpus}]
        else:      
            result['funded_from']=[]
        #result['sip_amount']=sip_amount
        #result['sip_years']=client_data['client_data']['retirement_age']-(current_date.year-int(client_data['client_data']['date_of_birth'].split('-')[0]))
        result['surplus']=0
    
    elif required_retirement_corpus==estimated_retirement_corpus:

        result={}
        result['goal_name']="retirement" 
        result['target_corpus']=required_retirement_corpus
        result['corpus_needed']=0 
        result['corpus_gap']=0 
        result['target_year']= current_year + years_to_retire
        if estimated_retirement_corpus>0:
            result['funded_from']=[{'future_values_retirement_investments':estimated_retirement_corpus}]
        else: 
            result['funded_from']=[]
        #result['sip_amount']=0
        #result['sip_years']=0
        result['surplus']=0
    
    elif required_retirement_corpus<estimated_retirement_corpus: 
#         print(f""" 
#              required retirement corpus: {required_retirement_corpus} \n estimated retirement corpus: {estimated_retirement_corpus} \n
#              retirement_gap = 0, \n surplus_corpus: {estimated_retirement_corpus-required_retirement_corpus}
# """)
        result={}
        result['goal_name']="retirement"
        result['target_corpus']=required_retirement_corpus
        result['corpus_needed']=0
        result['corpus_gap']=0
        result['target_year']= current_year + years_to_retire
        if estimated_retirement_corpus>0:
            result['funded_from']=[{'future_values_retirement_investments':estimated_retirement_corpus}]
        else: 
            result['funded_from']=[]
        #result['sip_amount']=0
        #result['sip_years']=0
        result['surplus']=estimated_retirement_corpus-required_retirement_corpus
    
    retirement_goal=[result]

    print(f"retirement_goal: {retirement_goal}\n")
    print("--------------------------"*6)
    return {'retirement_goal': retirement_goal}


def wealth_at_retirement(state: ClientState):
    """
    Aggregates the projected wealth available at the time of retirement.

    Combines the future values of every corpus-building source at the
    retirement year and returns a breakdown alongside the grand total:
        - Retirement schemes (EPF / PPF / NPS) from retirement_schemes_fv
        - Fixed deposits compounded to retirement
        - Real estate grown at 3% p.a. to retirement
        - Leftover ESOP/RSU pools (after goal allocation) grown to retirement
        - SIP / freed-SIP / lumpsum contributions earmarked for the
          retirement goal (from optimal_goal_allocation)

    Note: SSY is intentionally excluded for now.

    Returns:
        dict: {
            "wealth_at_retirement": {
                "retirement_year": int,
                "breakdown": { <source>: {"future_value": float, "rate": str}, ... },
                "total_corpus": float
            }
        }
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: wealth_at_retirement \n")
    print("Aggregating projected wealth at retirement... \n")

    client_data   = state.get('client_data', {})
    invest_detail = client_data.get('investment_details', {})
    ret_info      = state.get('required_retirement_corpus', {})
    client_info   = ret_info.get('client_info', {})
    years_to_ret  = client_info.get('years_to_retirement', 0)
    retirement_year = date.today().year + years_to_ret

    # ── 1. Retirement schemes (EPF / PPF / NPS) ──────────────────────────
    schemes_fv      = state.get('retirement_schemes_fv', {})
    category_totals = schemes_fv.get('category_totals', {})

    epf_fv  = category_totals.get('epf',  0)
    ppf_fv  = category_totals.get('ppf',  0)
    nps_fv  = category_totals.get('nps',  0)

    ret_investments = invest_detail.get('retirement_investments', {})
    epf_rate = f"{ret_investments.get('epf', [{}])[0].get('interest_rate', 0.085) * 100:.1f}%" if ret_investments.get('epf') else "8.5%"
    ppf_rate = f"{ret_investments.get('ppf', [{}])[0].get('interest_rate', 0.075) * 100:.1f}%" if ret_investments.get('ppf') else "7.5%"
    nps_rate = f"{ret_investments.get('nps', [{}])[0].get('expected_corpus_growth_rate', 0.10) * 100:.1f}%" if ret_investments.get('nps') else "10%"

    # ── 2. Fixed Deposits ────────────────────────────────────────────────
    fd_fv   = 0
    fd_rate = "-"
    for asset in state.get('liquid_assets', []):
        if 'fixed_deposits' in asset:
            fd = asset['fixed_deposits']
            principal  = fd.get('principal_amount', 0)
            rate       = fd.get('interest_rate', 0.065)
            fd_fv     += principal * ((1 + rate) ** years_to_ret)
            fd_rate    = f"{rate * 100:.1f}%"

    # ── 3. Real Estate (3% p.a. growth to retirement) ────────────────────
    real_estate_fv  = 0
    for asset in state.get('fixed_assets', []):
        if 'real_estate_investment' in asset:
            current_val    = asset['real_estate_investment'].get('current_market_value', 0)
            real_estate_fv += current_val * ((1.03) ** years_to_ret)

    # ── 3b. Leftover ESOP / RSU (remaining pools after goal allocation) ──
    oga_state = state.get('optimal_goal_allocation', {}) or {}
    goals_state = oga_state.get('goals', []) or []
    rsu_portfolio = oga_state.get('rsu_portfolio', []) or []

    esop_rate = 0.12
    esop_usable_cap = 0.60
    vested_total = sum(
        float(e.get('vested_esops_value', 0) or 0)
        for e in (invest_detail.get('esops') or [])
    )
    esop_usable = vested_total * esop_usable_cap
    esop_consumed = 0.0
    for goal in goals_state:
        for fund in goal.get('funded_from') or []:
            if fund.get('type') == 'esop_funds':
                esop_consumed += float(fund.get('pv_allocated_today', 0) or 0)
    esop_remaining = max(0.0, esop_usable - esop_consumed)
    esop_fv = calculate_future_value(esop_remaining, esop_rate, years_to_ret) if esop_remaining > 0 else 0.0

    rsu_rate = get_rsu_growth_rate(invest_detail)
    rsu_remaining = sum(float(p.get('rsu_remaining', 0) or 0) for p in rsu_portfolio)
    rsu_fv = calculate_future_value(rsu_remaining, rsu_rate, years_to_ret) if rsu_remaining > 0 else 0.0

    # ── 4. SIP / Lumpsum / Freed-SIP contributions for Retirement ────────
    sip_fv_retirement       = 0   # sip_from_surplus / sip_from_partial_surplus only
    freed_sip_fv_retirement = 0   # freed_sip (released EMI redirected to retirement)
    lumpsum_fv_retirement   = 0

    for goal in state.get('optimal_goal_allocation', {}).get('goals', []):
        if goal.get('goal_name', '').strip().lower() == 'retirement':
            for fund in goal.get('funded_from', []):
                ftype = fund.get('type', '')
                fv    = fund.get('fv_contribution', 0)
                if ftype in ('sip_from_surplus', 'sip_from_partial_surplus'):
                    sip_fv_retirement += fv
                elif ftype == 'freed_sip':
                    freed_sip_fv_retirement += fv
                elif ftype in ('lumpsum_from_liquid', 'lumpsum_from_liquid_partial'):
                    lumpsum_fv_retirement += fv

    # ── 5. Aggregate totals ──────────────────────────────────────────────
    total_corpus = (fd_fv + epf_fv + ppf_fv + nps_fv + real_estate_fv
                    + sip_fv_retirement + freed_sip_fv_retirement + lumpsum_fv_retirement
                    + esop_fv + rsu_fv)

    wealth_breakdown = {
        "epf":         {"future_value": round(epf_fv, 2),                 "rate": epf_rate},
        "ppf":         {"future_value": round(ppf_fv, 2),                 "rate": ppf_rate},
        "nps":         {"future_value": round(nps_fv, 2),                 "rate": nps_rate},
        "fixed_deposits": {"future_value": round(fd_fv, 2),              "rate": fd_rate},
        "real_estate": {"future_value": round(real_estate_fv, 2),        "rate": "3.0%"},
        "esop":        {"future_value": round(esop_fv, 2),               "rate": f"{esop_rate * 100:.1f}%"},
        "rsu":         {"future_value": round(rsu_fv, 2),                "rate": f"{rsu_rate * 100:.1f}%"},
        "sip":         {"future_value": round(sip_fv_retirement, 2),     "rate": "-"},
        "freed_sip":   {"future_value": round(freed_sip_fv_retirement, 2), "rate": "-"},
        "lumpsum":     {"future_value": round(lumpsum_fv_retirement, 2), "rate": "-"},
    }

    wealth = {
        "retirement_year": retirement_year,
        "breakdown":       wealth_breakdown,
        "total_corpus":    round(total_corpus, 2),
    }

    print(f"wealth_at_retirement: {wealth}\n")
    print("--------------------------"*6)
    return {'wealth_at_retirement': wealth}


def calculate_retirement_annuity(state: ClientState):
    """
    Income-preservation retirement annuity check: can the yield from the
    retirement-year corpus fund a desired monthly annuity without spending
    principal?

    Corpus base is `wealth_at_retirement.breakdown` — the single source of truth.
    Every bucket there is already grown to the retirement year, so nothing is
    re-compounded here. The one exception is existing mutual-fund holdings, which
    have no bucket in the breakdown and are still projected from investment_details.

    Priority order: ESOP → RSU → rental/other → FD → EPF/PPF → NPS → MF.
    SIP, freed-EMI and lumpsum are merged into the MF row (all MF-invested).
    Real-estate capital is excluded — its income is already counted as rental.

    Basis: NOMINAL throughout. The corpus is a retirement-year (future-value)
    figure and `desired_monthly_annuity` is likewise a future-value target, so
    yields use nominal rates (see POST_RETIREMENT_YIELD_RATES). Note these rates
    are applied in perpetuity, so life_expectancy does not enter the maths.

    Skips cleanly when desired_monthly_annuity is absent or <= 0.
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: calculate_retirement_annuity \n")
    print("Checking retirement annuity against asset income... \n")

    client_data = state.get("client_data", {})
    personal = client_data.get("client_data", {})
    desired_monthly_annuity = float(personal.get("desired_monthly_annuity", 0) or 0)
    if desired_monthly_annuity <= 0:
        print("Skipping retirement annuity — desired_monthly_annuity not set\n")
        print("--------------------------"*6)
        return {}

    retirement_age = personal.get("retirement_age", 60)
    invest = client_data.get("investment_details", {})
    fs = (invest.get("financial_summary") or [{}])[0]
    surplus_income_monthly = float(fs.get("other_income(rental/interest/other)", 0) or 0)

    ret_info = state.get("required_retirement_corpus", {})
    client_info = ret_info.get("client_info", {})
    years_to_ret = client_info.get("years_to_retirement", 0)

    war = state.get("wealth_at_retirement", {})
    retirement_year = war.get("retirement_year") or (date.today().year + years_to_ret)

    # ── Corpus base: wealth_at_retirement.breakdown ─────────────────────────
    # Single source of truth. Every bucket is already grown to the retirement
    # year there, so nothing is re-derived or re-compounded here.
    breakdown = (war.get("breakdown") or {})

    def _bucket_fv(key: str) -> float:
        return float((breakdown.get(key) or {}).get("future_value", 0) or 0)

    def _bucket_rate(key: str, default: float) -> float:
        """Post-retirement yield rate: explicit override first, else the
        bucket's own stored rate, else `default`. Buckets carrying "-" (sip /
        freed_sip / lumpsum) have no stored rate and fall through to the
        override."""
        if key in POST_RETIREMENT_YIELD_RATES:
            return POST_RETIREMENT_YIELD_RATES[key]
        return _parse_rate_string((breakdown.get(key) or {}).get("rate"), default)

    # ── 1. ESOP yield (leftover pool after goal allocation) ─────────────────
    esop_fv = _bucket_fv("esop")
    esop_rate = _bucket_rate("esop", 0.12)
    esop_income = esop_fv * esop_rate

    # ── 2. RSU yield (leftover tracker pool after goal allocation) ──────────
    rsu_fv = _bucket_fv("rsu")
    rsu_rate = _bucket_rate("rsu", get_rsu_growth_rate(invest))
    rsu_income = rsu_fv * rsu_rate

    # ── 3. Rental / other income (face value, not grown) ────────────────────
    # Real estate CAPITAL is excluded from the corpus base on purpose — the same
    # property must not both pay rent and yield on its market value.
    rental_annual = surplus_income_monthly * 12

    # ── 4. FD interest ──────────────────────────────────────────────────────
    fd_fv = _bucket_fv("fixed_deposits")
    fd_rate_str = (breakdown.get("fixed_deposits") or {}).get("rate", "6.5%")
    fd_rate = _parse_rate_string(fd_rate_str, 0.065)
    fd_income = fd_fv * fd_rate

    # ── 5. Retirement schemes (EPF / PPF / NPS) ─────────────────────────────
    epf_ppf_fv = _bucket_fv("epf") + _bucket_fv("ppf")
    epf_ppf_rate = POST_RETIREMENT_YIELD_RATES["epf"]
    epf_ppf_income = epf_ppf_fv * epf_ppf_rate

    nps_fv = _bucket_fv("nps")
    nps_rate = POST_RETIREMENT_YIELD_RATES["nps"]
    nps_income = nps_fv * nps_rate

    # ── 6. Mutual funds — existing holdings + SIP + freed-EMI + lumpsum ─────
    # Merged into one row: all four are MF-invested and share a single rate.
    # Existing MF holdings have no bucket in wealth_at_retirement, so they are
    # still compounded from investment_details here.
    existing_mf_fv = sum(
        calculate_future_value(
            float(mf.get("current_value", 0) or 0),
            float(mf.get("expected_annual_return", 0.10) or 0.10),
            years_to_ret,
        )
        for mf in (invest.get("mutual_funds") or [])
        if float(mf.get("current_value", 0) or 0) > 0
    )
    mf_fv = (
        existing_mf_fv
        + _bucket_fv("sip")
        + _bucket_fv("freed_sip")
        + _bucket_fv("lumpsum")
    )
    mf_rate = POST_RETIREMENT_YIELD_RATES["mutual_funds"]
    mf_income = mf_fv * mf_rate
    mf_rate_str = f"{mf_rate * 100:.1f}%"

    def _source_row(
        key: str,
        label: str,
        rate: str,
        annual_income: float,
        corpus_fv: float | None,
        remaining_base: float | None,
        required: bool,
    ) -> dict:
        return {
            "key": key,
            "label": label,
            "rate": rate,
            "monthly_income": round(annual_income / 12, 2),
            "annual_income": round(annual_income, 2),
            "corpus_fv": round(corpus_fv, 2) if corpus_fv else None,
            "remaining_base": round(remaining_base, 2) if remaining_base else None,
            "required": required,
        }

    ordered_candidates = [
        ("esop", "ESOP yield", f"{esop_rate * 100:.1f}%", esop_income, esop_fv if esop_fv else None, None),
        ("rsu", "RSU yield", f"{rsu_rate * 100:.1f}%", rsu_income, rsu_fv if rsu_fv else None, None),
        ("rental_other_income", "Rental / other income", "-", rental_annual, None, None),
        ("fixed_deposits", "FD interest", fd_rate_str, fd_income, fd_fv if fd_fv else None, None),
        ("epf_ppf", "EPF / PPF yield", f"{epf_ppf_rate * 100:.1f}%", epf_ppf_income, epf_ppf_fv if epf_ppf_fv else None, None),
        ("nps", "NPS yield", f"{nps_rate * 100:.1f}%", nps_income, nps_fv if nps_fv else None, None),
        ("mutual_funds", "Mutual fund yield", mf_rate_str, mf_income, mf_fv if mf_fv else None, None),
    ]

    desired_annual = desired_monthly_annuity * 12

    # Achievability is judged on the FULL (uncapped) yield capacity of every source.
    full_total_annual = sum(
        annual_income for (_k, _l, _r, annual_income, _c, _b) in ordered_candidates
        if annual_income > 0
    )
    achievable = full_total_annual >= desired_annual

    # Display only the sources actually drawn on, in priority order, each capped to
    # the remaining need. Once the desired annuity is met, the remaining (cheaper-
    # ranked) sources are unused and omitted entirely.
    sources: list[dict] = []
    cumulative = 0.0
    for key, label, rate_str, annual_income, corpus_fv, remaining_base in ordered_candidates:
        if annual_income <= 0:
            continue
        remaining_need = desired_annual - cumulative
        if remaining_need <= 0:
            break
        used = min(annual_income, remaining_need)
        cumulative += used
        sources.append(
            _source_row(key, label, rate_str, used, corpus_fv, remaining_base, True)
        )

    used_total_annual = cumulative
    max_monthly = full_total_annual / 12 if full_total_annual > 0 else 0.0
    used_monthly = used_total_annual / 12
    shortfall_monthly = max(0.0, desired_monthly_annuity - max_monthly)
    achievable_monthly = desired_monthly_annuity if achievable else used_monthly

    result = {
        "model": "income_preservation",
        "retirement_year": retirement_year,
        "retirement_age": retirement_age,
        "life_expectancy": 85,
        "desired_monthly_annuity": round(desired_monthly_annuity, 2),
        "achievable": achievable,
        "achievable_monthly_annuity": round(achievable_monthly, 2),
        "max_monthly_annuity": round(max_monthly, 2),
        "shortfall_monthly": round(shortfall_monthly, 2),
        "surplus_income_monthly": round(surplus_income_monthly, 2),
        "total_available_monthly": round(used_monthly, 2),
        "corpus_base": round(
            esop_fv + rsu_fv + fd_fv + epf_ppf_fv + nps_fv + mf_fv, 2
        ),
        "excluded_buckets": sorted(ANNUITY_EXCLUDED_BUCKETS),
        "sources": sources,
    }

    print(f"retirement_annuity: {result}\n")
    print("--------------------------"*6)
    return {"retirement_annuity": result}
