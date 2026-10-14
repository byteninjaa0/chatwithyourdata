"""final_state -> client values JSON for the 49-slide Goal Based Planning deck.

A translator, not a calculator. Every figure is read from the workflow's
final_state. Presentation arithmetic (shares of a total, sums of rows,
display formatting) happens here; the one projection the deck needs that the
state does not store -- an EPF, PPF or NPS balance at an intermediate year for
the bar charts -- is computed with the workflow's own functions, so the bars
end exactly on the workflow's figure.

Which slides appear follows the rules of the previous builder (ppt_runner.py, git tag legacy-ppt-pipeline):
a section is included only when the client has the data behind it -- loans,
children at UG and/or PG stage, a marriage goal, SSY, EPF/PPF/NPS, policies,
FDs. Sections the workflow produces no data for (the cover classification
and suggestions, the deposit-funded prepayment story, direct-equity holding
detail, legacy, the executive summary) are left out rather than shown with
sample text.

Commentary tokens are filled with short factual sentences built from the
same figures. Nothing is written that the numbers do not say.
"""

import re
from datetime import date, datetime

from Financial_Planning.Utilities.utility_functions import (
    epf_future_value, nps_future_value, ppf_future_value,
)

from .schema import Include, PlanValues

DASH = "—"


# ----------------------------------------------------------------- helpers

def _number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(value):
    """House style: 14700000 -> '₹1.47 Cr', 380000 -> '₹3.8 L', 4805 -> '₹4,805'."""
    amount = _number(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 1e7:
        return f"{sign}₹{amount / 1e7:.2f} Cr"
    if amount >= 1e5:
        return f"{sign}₹{amount / 1e5:.1f} L"
    return sign + _rupees(amount)


def _rupees(value):
    """Exact rupees with Indian digit grouping: '₹2,20,000'."""
    amount = int(round(_number(value)))
    text = str(abs(amount))
    if len(text) > 3:
        head, tail = text[:-3], text[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        text = head + "," + tail
    return "₹" + ("-" if amount < 0 else "") + text


def _pct(fraction, digits=0):
    return f"{_number(fraction) * 100:.{digits}f}%"


def _rate(value):
    """A rate stored as 0.0925 or 9.25 -> '9.25%'."""
    r = _number(value)
    if r and r < 1:
        r *= 100
    return f"{r:.2f}".rstrip("0").rstrip(".") + "%"


def _year_of(value):
    m = re.search(r"(19|20)\d\d", str(value or ""))
    return int(m.group(0)) if m else None


def _fmt_date(value):
    """'12 March 1981' from an ISO or Indian-order date."""
    if value in (None, ""):
        return ""
    if isinstance(value, (date, datetime)):
        return f"{value.day} {value:%B %Y}"
    for pattern in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %B %Y"):
        try:
            parsed = datetime.strptime(str(value).strip(), pattern)
        except ValueError:
            continue
        return f"{parsed.day} {parsed:%B %Y}"
    return str(value)


def _month_year(value):
    """'Nov 2029' from a date string, or the year alone."""
    for pattern in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return f"{datetime.strptime(str(value).strip(), pattern):%b %Y}"
        except ValueError:
            continue
    y = _year_of(value)
    return str(y) if y else DASH


def _honorific(name, prefix):
    name = str(name or "").strip()
    if not name:
        return ""
    if name.split(".")[0].lower().rstrip(".") in ("mr", "mrs", "ms", "dr"):
        return name
    return f"{prefix} {name}"


def _words(n):
    words = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight",
             "nine", "ten", "eleven", "twelve"]
    n = int(n)
    return words[n] if 0 <= n < len(words) else str(n)


def _client(fs):
    return fs.get("client_data", {}).get("client_data", {})


def _investments(fs):
    return fs.get("client_data", {}).get("investment_details", {})


def _financial_summary(fs):
    summary = _investments(fs).get("financial_summary") or {}
    if isinstance(summary, list):
        summary = summary[0] if summary else {}
    return summary


def _client_info(fs):
    return (fs.get("required_retirement_corpus") or {}).get("client_info", {}) or {}


def _goals(fs):
    return (fs.get("optimal_goal_allocation") or {}).get("goals", []) or []


def _latest_funding(fs):
    snapshots = fs.get("goal_funding") or []
    return snapshots[-1] if snapshots else {}


def _today_year(review_on):
    return review_on.year


def _retirement_year(fs, review_on):
    client = _client(fs)
    age, retire = client.get("client_age"), client.get("retirement_age")
    if isinstance(age, int) and isinstance(retire, int):
        return review_on.year + retire - age
    years = _client_info(fs).get("years_to_retirement")
    return review_on.year + int(years) if years else None


# ----------------------------------------------------------- goal sources

SIP_KINDS = ("sip_from_surplus", "sip_from_partial_surplus")
LUMPSUM_KINDS = ("lumpsum_from_liquid", "lumpsum_from_liquid_partial")


def _sip_today(goal, year):
    """Monthly SIP a goal draws from today's surplus (freed EMIs come later)."""
    return sum(_number(s.get("monthly")) for s in goal.get("funded_from") or []
               if isinstance(s, dict) and s.get("type") in SIP_KINDS
               and (_year_of(s.get("from_year")) or year) <= year)


def _source_value(s):
    """What a funding source contributes at the goal year. SIPs, freed EMIs and
    lumpsums record fv_contribution; SSY and ESOP withdrawals record amount_used."""
    return _number(s.get("fv_contribution")) or (
        _number(s.get("amount_used")) if s.get("type") in ("ssy_funds", "esop_funds") else 0.0)


def _reached(goal):
    return sum(_source_value(s) for s in goal.get("funded_from") or [] if isinstance(s, dict))


def _source_groups(goal):
    """A goal's funding grouped by kind, as (label, terms, value) rows.

    The workflow can fund one goal from several freed EMIs or SIP tranches;
    the deck shows one row per kind of money, which is how a client reads it.
    """
    groups = {}
    order = []

    def add(key, label, terms, value):
        if key not in groups:
            groups[key] = [label, terms, 0.0]
            order.append(key)
        groups[key][2] += value

    for s in goal.get("funded_from") or []:
        if not isinstance(s, dict):
            continue
        kind, value = str(s.get("type", "")), _source_value(s)
        if not value:
            continue
        start, end, rate = s.get("from_year"), s.get("to_year"), s.get("rate")
        span = f"{start}–{end}" if start and end else ""
        if kind in SIP_KINDS:
            add("sip", f"SIP {_rupees(s.get('monthly'))} a month",
                " · ".join(p for p in (f"{rate} assumed" if rate else "", span) if p), value)
        elif kind == "freed_sip":
            add("freed", "Freed EMIs re-tagged",
                f"{_rupees(s.get('monthly'))} a month from {start}" if start else "", value)
        elif kind in LUMPSUM_KINDS:
            add("lump", f"Lumpsum {_money(s.get('principal_used_today'))} from liquid assets",
                f"{rate} to {end}" if rate and end else "", value)
        elif kind == "esop_funds":
            add("esop", str(s.get("source") or "Vested ESOPs"), "", value)
        elif kind == "ssy_funds":
            add("ssy", "Sukanya Samriddhi withdrawal",
                "at maturity" if "maturity" in str(s.get("withdrawal_type", "")) else "50% for higher education",
                value)
        else:
            add(kind, kind.replace("_", " ").capitalize() or "Allocation", "", value)
    # The SIP label states today's instalment; several tranches sum into it.
    sips = [s for s in goal.get("funded_from") or [] if isinstance(s, dict) and s.get("type") in SIP_KINDS]
    if len(sips) > 1 and "sip" in groups:
        groups["sip"][0] = f"SIP {_rupees(sum(_number(s.get('monthly')) for s in sips))} a month"
    return [tuple(groups[k]) for k in order]


def _fit(rows, slots):
    """At most `slots` rows; anything beyond folds into one 'Other sources'."""
    if len(rows) <= slots:
        return rows
    keep, rest = rows[:slots - 1], rows[slots - 1:]
    return keep + [("Other sources", "", sum(r[2] for r in rest))]


def _goal_status(goal):
    """A short note on whether the goal is met, postponed or short."""
    gap = _number(goal.get("corpus_gap"))
    kind = ((goal.get("filter") or [{}])[0] or {}).get("type", "")
    note = goal.get("note")
    if kind == "postponed" and isinstance(note, dict):
        years = int(note.get("postponed_years", 1) or 1)
        return f"Postponed {years} year{'s' if years != 1 else ''} to {note.get('to_year')} so it can be fully funded."
    if gap > 0:
        return f"{_money(gap)} is still to be funded."
    return "Fully funded on these assumptions."


def _today_cost(fs, goal):
    """Cost today for a goal, from the intake's financial_goals.

    Matched on target year and amount first: the workflow's goal-ordering LLM
    can rewrite a goal's name (the intake's "Vaccation" comes back as
    "Vacation"), but the year and the amount at that year come through
    unchanged. A name match is the fallback.
    """
    intake = fs.get("client_data", {}).get("financial_goals") or []
    year, amount = goal.get("target_year"), _number(goal.get("target_corpus"))
    for g in intake:
        if (g.get("target_year") == year and amount
                and abs(_number(g.get("capital_required_at_target_year")) - amount) < 1):
            return _number(g.get("capital_required_today"))
    name = str(goal.get("goal_name", "")).strip().lower()
    for g in intake:
        if str(g.get("goal_name", "")).strip().lower() == name:
            return _number(g.get("capital_required_today"))
    return 0.0


def _implied_rate(today, future, years):
    if today and future and years:
        return (future / today) ** (1 / years) - 1
    return None


# ----------------------------------------------------------- slide 1, 2

SUMMARY_GROUPS = (
    (("marriage", "wedding"), "Kid's Marriage"),
    (("retirement",), "Retirement"),
    (("vacation", "vaccation", "travel", "holiday"), "Vacation"),
    (("home", "house", "property", "renovation", "flat", "plot"), "Home"),
    (("car", "vehicle"), "Vehicle"),
    (("emergency",), "Emergency"),
)


def _summary_goal_name(name):
    if _education_stage(name):
        return "Kid's Education"
    lowered = str(name or "").lower()
    for words, label in SUMMARY_GROUPS:
        if any(w in lowered for w in words):
            return label
    text = str(name or "").strip()
    return text if len(text) <= 20 else text.split(" ")[0][:20]


def _personal(fs, review_on):
    client = _client(fs)
    spouse = _honorific(client.get("spouse_name"), "Mrs.")
    name = _honorific(client.get("name"), "Mr.")
    values = {
        "client_display_name": f"Mr. & Mrs. {client.get('name')}" if spouse else name,
        "review_date": f"{review_on:%B %Y}",
        "client_name": name,
        "client_dob": _fmt_date(client.get("date_of_birth")),
        "client_age": str(client.get("client_age") or ""),
        "retirement_age": str(client.get("retirement_age") or ""),
        "spouse_name": spouse or DASH,
        "spouse_dob": _fmt_date(client.get("spouse_dob")) or DASH,
        "children_names_ages": "       ".join(
            f"{i}. {c.get('child_name', '')}, {c.get('child_age')}"
            for i, c in enumerate(client.get("children") or [], 1)) or DASH,
    }
    appetite = fs.get("risk_appetite")
    values["risk_appetite"] = str(appetite.get("risk_appetite", "")) if isinstance(appetite, dict) else str(appetite or "")
    ry = _retirement_year(fs, review_on)
    if ry:
        values["retirement_year"] = str(ry)

    years_by = {}
    for g in _goals(fs):
        label = _summary_goal_name(g.get("goal_name"))
        if label and g.get("target_year"):
            years_by.setdefault(label, set()).add(str(g["target_year"]))
    rows = sorted(years_by.items(), key=lambda kv: min(kv[1]))[:3]
    values["summary_goal"] = [{"name": n, "years": " · ".join(sorted(ys))} for n, ys in rows]
    return values


# ----------------------------------------------------- slides 3, 4, 7

def _existing_sips(fs):
    """Monthly SIPs the client already runs (investment_details.mutual_funds
    sip_amount). The workflow deducts these from the surplus as a committed
    outflow before planning (get_existing_monthly_sip), so the deck counts
    them as committed savings alongside the plan's new SIPs."""
    return sum(_number(mf.get("sip_amount")) for mf in _investments(fs).get("mutual_funds") or []
               if isinstance(mf, dict))


def _cashflow(fs, review_on):
    fsum = _financial_summary(fs)
    income = _number(fsum.get("monthly_salary")) + _number(fsum.get("other_income(rental/interest/other)"))
    expenses = _number(fsum.get("monthly_expenses_excl_emis")) or _number(_client_info(fs).get("current_monthly_expenses"))
    emis = sum(_number(l.get("emi_amount")) for l in fs.get("liabilities") or [] if isinstance(l, dict))
    new_sips = sum(_sip_today(g, review_on.year) for g in _goals(fs))
    existing = _existing_sips(fs)
    sips = new_sips + existing
    if not income:
        return {}
    surplus = income - expenses - emis - sips
    shares = _apportion({"expenses": expenses, "emis": emis, "savings": sips}, income)

    kinds = []
    for l in fs.get("liabilities") or []:
        kind = re.sub(r"\s*loan\s*$", "", str(l.get("type", "")), flags=re.I).strip().lower()
        if kind and kind not in kinds:
            kinds.append(kind)

    values = {
        "gross_monthly_income": _rupees(income),
        "gross_monthly_income_short": _money(income),
        "monthly_expenses": _rupees(expenses),
        "expenses_pct": shares["expenses"],
        "emis_pct": shares["emis"],
        "savings_pct": shares["savings"],
        "emi_note": (" and ".join([", ".join(kinds[:-1]), kinds[-1]]) if len(kinds) > 1 else kinds[0]) + " loan"
                    + ("s" if len(kinds) > 1 else "") if kinds else "no loans",
        "monthly_surplus": _rupees(surplus) if surplus > 0 else "Nil",
    }
    parts = [f"{_money(expenses)} to household expenses"]
    if emis:
        parts.append(f"{_money(emis)} to EMIs")
    if existing:
        parts.append(f"{_money(existing)} to existing SIPs")
    parts.append(f"{_money(new_sips)} to goal SIPs" if new_sips else "nothing yet to goal SIPs")
    sentence = f"Of {_money(income)} coming in each month, " + ", ".join(parts[:-1]) + f" and {parts[-1]}."
    if surplus > 0:
        sentence += f" {_rupees(surplus)} a month is left unallocated."
    elif surplus < 0:
        sentence += f" Commitments exceed income by {_rupees(-surplus)} a month."
    values["cashflow_comment"] = sentence

    # Slide 7 -- diagnostic. Emergency reserve is liquid assets over a month's
    # outgoings (expenses and EMIs).
    liquid = _number(fs.get("liquid_pool"))
    outgo = expenses + emis
    months = liquid / outgo if outgo else 0
    values["emergency_reserve"] = f"{months:.0f} months" if months >= 1 else "Under a month"
    score = _health_score(sips / income, emis / income, months,
                          _number((fs.get("financial_overview") or {}).get("liquidity_ratio")))
    values["health_score"] = f"{score}%"
    tone = "strong" if score >= 75 else "stable" if score >= 55 else "under strain"
    values["health_summary"] = (
        f"Your financial health is {tone}, with a score of {score}%. "
        f"{shares['savings']} of income goes to goal SIPs, EMIs take {shares['emis']}, "
        f"and liquid assets cover {values['emergency_reserve'].lower()} of outgoings.")
    return values


def _health_score(savings_rate, emi_ratio, reserve_months, liquidity_ratio):
    """0-100, the mean of four sub-scores, each capped at 1:
    savings rate against 30% of income, EMIs under 30% of income (zero at
    60%), an emergency reserve against six months, and liquid assets against
    30% of the total. Stated here so the gauge can be explained."""
    parts = [
        min(1.0, savings_rate / 0.30),
        1.0 if emi_ratio <= 0.30 else max(0.0, 1 - (emi_ratio - 0.30) / 0.30),
        min(1.0, reserve_months / 6),
        min(1.0, liquidity_ratio / 0.30),
    ]
    return int(round(100 * sum(parts) / len(parts)))


def _apportion(parts, whole):
    """Whole-number shares of `whole` that add up, never past 100%."""
    if not whole:
        return {k: "0%" for k in parts}
    exact = {k: 100 * v / whole for k, v in parts.items()}
    floors = {k: int(v) for k, v in exact.items()}
    target = min(100, int(round(sum(exact.values()))))
    short = target - sum(floors.values())
    for k in sorted(exact, key=lambda k: -(exact[k] - floors[k]))[:max(0, short)]:
        floors[k] += 1
    if sum(exact.values()) > 100:
        # Commitments above income: each share stays true to income, so they
        # add past 100% and the comment says by how much.
        floors = {k: int(round(v)) for k, v in exact.items()}
    return {k: f"{v}%" for k, v in floors.items()}


# --------------------------------------------------------- slides 4, 5, 6

VALUE_FIELDS = ("current_value", "portfolio_value", "principal_amount", "vested_esops_value",
                "current_market_value", "investment_amount", "maturity_value")
ASSET_KEYS = {"real_estate_investment": "real_estate", "esops": "esops"}


def _instrument_value(details):
    if not isinstance(details, dict):
        return _number(details)
    for field in VALUE_FIELDS:
        if field in details:
            return _number(details[field])
    return 0.0


def _assets(fs):
    totals = {}
    for bucket in ("retirement_assets", "liquid_assets", "fixed_assets"):
        for entry in fs.get(bucket) or []:
            if not isinstance(entry, dict):
                continue
            for asset_type, details in entry.items():
                if asset_type == "ulip":  # insurance-linked: shown under policies
                    continue
                value = _instrument_value(details)
                if value:
                    key = ASSET_KEYS.get(asset_type, asset_type)
                    totals[key] = totals.get(key, 0.0) + value
    ssy = _ssy_holdings(fs)
    if ssy:
        totals["ssy"] = sum(_number(s.get("current_value")) for _, s in ssy) or totals.get("ssy", 0)
        if not totals["ssy"]:
            totals.pop("ssy")
    values = {"assets": {k: {"amount": float(round(v))} for k, v in totals.items()}}

    overview = (fs.get("financial_overview") or {}).get("category_percentage") or {}
    if totals:
        biggest = max(totals, key=totals.get)
        share = totals[biggest] / sum(totals.values())
        label = biggest.replace("_", " ")
        values["allocation_comment"] = (
            f"{label.capitalize()} is the largest holding at {share:.0%} of assets. "
            f"Liquid assets are {overview.get('liquid', 0):.0f}% of the total, which is what the goals can draw on.")
    retire = [k.upper() for k in ("epf", "ppf", "nps") if k in totals]
    values["bucket_retirement_desc"] = (
        f"{', '.join(retire)} are long-lock assets, counted towards retirement only." if retire
        else "No dedicated retirement assets are held today.")
    return values


def _ssy_holdings(fs):
    out = []
    for child in _client(fs).get("children") or []:
        for inv in child.get("investments") or []:
            if str(inv.get("type", "")).strip().upper() == "SUKANYA SAMRIDDHI YOJANA":
                out.append((child, inv))
    return out


# ------------------------------------------------------- slides 8, 9

def _loans(fs, review_on):
    plans = (fs.get("optimal_loan_allocation") or {}).get("per_loan") or []
    rows = []
    for i, l in enumerate(x for x in fs.get("liabilities") or [] if isinstance(x, dict)):
        kind = str(l.get("type") or "Loan").strip()
        plan = next((p for p in plans if str(p.get("type")) == kind), plans[i] if i < len(plans) else {})
        outstanding, emi = _number(l.get("outstanding_balance")), _number(l.get("emi_amount"))
        base_m, fast_m = _number(plan.get("baseline_months")), _number(plan.get("accelerated_months"))
        close, new_close = _year_of(plan.get("baseline_close_date")), _year_of(plan.get("accelerated_close_date"))
        lump, extra = _number(plan.get("lump_sum_applied")), _number(plan.get("avg_monthly_extra_applied"))
        saved = _number(plan.get("interest_saved"))
        years_saved = (base_m - fast_m) / 12 if base_m and fast_m else 0
        row = {
            "name": kind.title(),
            "type": kind.title(),
            "outstanding": _rupees(outstanding),
            "emi": _rupees(emi),
            "rate": _rate(l.get("interest_rate")),
            "closing_year": str(close or DASH),
            "new_closing_year": str(new_close or close or DASH),
            "prepay_amount": _rupees(lump) if lump else "Nil",
            "emi_topup": f"{_rupees(extra)} a month" if extra else "Nil",
            "interest_outstanding": _rupees(max(0.0, emi * base_m - outstanding)) if base_m else DASH,
            "interest_saved": _rupees(saved) if saved else "Nil",
            "years_saved": (f"{years_saved:.0f} years" if abs(years_saved - round(years_saved)) < 0.05
                            else f"{years_saved:.1f} years") if years_saved > 0 else "None",
        }
        if saved and new_close and close and new_close < close:
            how = " and ".join(p for p in (f"prepaying {_money(lump)} now" if lump else "",
                                           f"adding about {_rupees(extra)} a month" if extra else "") if p)
            row["comment"] = (f"At {row['rate']}, {how or 'the planned prepayments'} closes the loan in "
                              f"{new_close} instead of {close}, saving {_money(saved)} of interest.")
        else:
            row["comment"] = f"No prepayment is planned; the loan runs to {close or 'term'} on the current EMI."
        rows.append(row)
    return rows


# ----------------------------------------------------- slides 10 - 14

def _goals_section(fs, review_on):
    year = review_on.year
    goals = _goals(fs)
    values = {}
    sips = sum(_sip_today(g, year) for g in goals)
    gap = sum(_number(g.get("corpus_gap")) for g in goals)
    values["new_saving_required"] = "Nil" if gap <= 0 else f"{_money(gap)} short"
    years = [g.get("target_year") for g in goals if g.get("target_year")]
    if goals and years:
        span = max(years) - year
        values["goals_section_intro"] = (
            f"{_words(len(goals)).capitalize()} goal{'s' if len(goals) != 1 else ''} over {_words(span) if span <= 12 else span} "
            f"years, mapped against the {_money(sips)} a month already committed to them and every instalment "
            f"that comes free along the way.")
        values["goals_funding_intro"] = (
            f"{_words(len(goals)).capitalize()} goal{'s' if len(goals) != 1 else ''}, in the order the money is needed. "
            "Each slide states the target in the year it falls due, and the sources that meet it.")

    # Road-map
    values["roadmap"] = [
        {"year": str(g["target_year"]), "label": _display_goal_name(g.get("goal_name")),
         "amount": f"{_money(g.get('target_corpus'))} at goal year"}
        for g in goals if g.get("target_year")]

    # Investment allocation: one row per kind of money, with the goals it funds.
    rows = {}

    def row(key, asset):
        return rows.setdefault(key, {"asset": asset, "current": 0.0, "allocated": 0.0, "monthly": 0.0, "goals": []})

    for g in goals:
        label = _short_goal_name(g.get("goal_name"))
        for s in g.get("funded_from") or []:
            if not isinstance(s, dict):
                continue
            kind = s.get("type", "")
            if kind in SIP_KINDS:
                r = row("sip", "New SIPs from surplus")
                r["monthly"] += _number(s.get("monthly")) if (_year_of(s.get("from_year")) or year) <= year else 0
            elif kind == "freed_sip":
                r = row("freed", "Freed EMIs, re-tagged")
            elif kind in LUMPSUM_KINDS:
                r = row("lump", "Liquid assets (MF, equity, FDs)")
                r["allocated"] += _number(s.get("principal_used_today"))
            elif kind == "esop_funds":
                r = row("esop", "Vested ESOPs")
                r["allocated"] += _number(s.get("amount_used") or s.get("principal_used_today"))
            elif kind == "ssy_funds":
                r = row("ssy", "Sukanya Samriddhi")
            else:
                continue
            if label not in r["goals"]:
                r["goals"].append(label)
        for s in g.get("sourced_from") or []:
            if s.get("source") == "future_values_retirement_investments":
                r = row("retire", "EPF · PPF · NPS")
                if label not in r["goals"]:
                    r["goals"].append(label)
    if "ssy" in rows:
        # The SSY accounts themselves: today's balance, all of it tagged to
        # the daughters' goals, and the yearly deposit as a monthly figure.
        held = [inv for _, inv in _ssy_holdings(fs)]
        rows["ssy"]["current"] = rows["ssy"]["allocated"] = sum(_number(i.get("current_value")) for i in held)
        rows["ssy"]["monthly"] = sum(_number(i.get("annual_contribution")) for i in held) / 12
    if "freed" in rows:
        # Freed EMIs are future money: say from when (the freed-cash-flow
        # slide names the loans). Their amounts stay out of the monthly
        # column, which totals what is invested today.
        plans = (fs.get("optimal_loan_allocation") or {}).get("per_loan") or []
        years = sorted(y for y in (_year_of(p.get("accelerated_close_date"))
                                   for p in plans if p.get("freed_by_year")) if y)
        if years:
            rows["freed"]["asset"] = f"Freed EMIs from {years[0]}"
    if "lump" in rows:
        rows["lump"]["current"] = _number(fs.get("liquid_pool"))
    if "retire" in rows:
        held = [d for e in fs.get("retirement_assets") or [] for k, d in e.items() if k in ("epf", "ppf", "nps")]
        rows["retire"]["current"] = rows["retire"]["allocated"] = sum(_instrument_value(d) for d in held)
        rows["retire"]["monthly"] = sum(
            _number(d.get("employee_employer_contribution_monthly")) + _number(d.get("monthly_contribution"))
            + _number(d.get("annual_contribution")) / 12 for d in held)
    existing = _existing_sips(fs)
    if existing:
        r = row("existing", "Existing MF SIPs")
        r["monthly"] = existing
        r["goals"] = ["Not tagged to a goal"]
    values["ia"] = [{
        "asset": r["asset"],
        "current": _money(r["current"]) if r["current"] else DASH,
        "allocated": _money(r["allocated"]) if r["allocated"] else DASH,
        "monthly": _rupees(r["monthly"]) if r["monthly"] else DASH,
        "goals": " · ".join(r["goals"]),
    } for r in rows.values()]
    if values["ia"]:
        values["investment_allocation_comment"] = (
            f"{_rupees(sips)} a month goes into new SIPs today"
            + (f", on top of {_rupees(existing)} in SIPs already running" if existing else "")
            + "; freed EMIs and existing holdings carry the rest.")

    # SIP allocation: today's instalment per goal.
    sip_rows = sorted(((g, _sip_today(g, year)) for g in goals), key=lambda t: -t[1])
    values["sip"] = [{"label": f"{_display_goal_name(g.get('goal_name'))} {g.get('target_year')}",
                      "amount": _rupees(m)} for g, m in sip_rows if m]
    if existing:
        values["sip"].append({"label": "Existing MF SIPs", "amount": _rupees(existing)})
    if values["sip"]:
        top = values["sip"][0]
        values["sip_comment"] = f"The largest instalment is {top['amount']} towards {top['label']}."

    # Freed cash flow: instalments that come free, re-tagged to retirement.
    funding = _latest_funding(fs) or fs.get("optimal_goal_allocation") or {}
    schedule = (fs.get("optimal_goal_allocation") or {}).get("ending_freed_sip_schedule") or funding.get("ending_freed_sip_schedule") or {}
    closing = {}
    for p in (fs.get("optimal_loan_allocation") or {}).get("per_loan") or []:
        closing.setdefault(str(_year_of(p.get("accelerated_close_date"))), []).append(str(p.get("type", "Loan")).lower())
    freed = []
    for yr in sorted(schedule, key=str):
        amount = _number(schedule[yr])
        if amount:
            what = closing.get(str(yr))
            event = (" and ".join(what).capitalize() + " closes") if what else "Goal instalment ends"
            freed.append({"year": str(yr), "event": event, "amount": _rupees(amount)})
    values["freed"] = freed[:4]
    retirement_sip = sum(_sip_today(g, year) for g in goals if "retirement" in str(g.get("goal_name", "")).lower())
    values["retirement_sip_today"] = _rupees(retirement_sip)
    committed = sips + existing
    values["monthly_savings"] = values["monthly_savings_short"] = _rupees(committed) if committed else "Nil"
    if not values["sip"]:
        values["sip_comment"] = "No new SIP is needed from today's surplus; existing holdings fund the goals."
    if not freed:
        ry = _retirement_year(fs, review_on)
        values["retirement_sip_final"] = _rupees(retirement_sip)
        values["retirement_sip_final_year"] = str(ry or "")
        values["freed_cashflow_comment"] = "No instalment comes free before retirement, so the retirement SIP stays level."
        values["ladder_headline"] = f"The retirement SIP holds at {_rupees(retirement_sip)} a month to {ry}"
        values["ladder_comment"] = "No EMI or goal instalment ends before retirement, so there is nothing to re-tag."
    if freed:
        final = retirement_sip + sum(_number(r["amount"].replace("₹", "").replace(",", "")) for r in freed[:4])
        values["freed_cashflow_comment"] = (
            f"Each instalment is re-tagged to retirement the month it is freed, lifting the retirement SIP "
            f"from {_rupees(retirement_sip)} to {_rupees(final)} by {freed[min(3, len(freed) - 1)]['year']}.")
        values["ladder_headline"] = (
            f"Every instalment that ends is re-tagged, lifting the retirement SIP to {_money(final)} "
            f"by {freed[min(3, len(freed) - 1)]['year']}")
        values["ladder_comment"] = (
            "Nothing here asks the family to spend less. Each step is money already leaving the account as an "
            "EMI or a goal contribution, redirected on the day it is freed.")
    return values


def _short_goal_name(name):
    """'Aarav PG', 'Retirement', 'Vacation' -- for a narrow column."""
    text = str(name or "").strip()
    stage = _education_stage(text)
    if stage:
        return f"{_child_of(text)} {stage.upper()}"
    return (text[:1].upper() + text[1:])[:18]


def _display_goal_name(name):
    """'Aarav UG' -> 'Aarav — undergraduate'; 'retirement' -> 'Retirement'."""
    text = str(name or "").strip()
    stage = _education_stage(text)
    if stage:
        return f"{_child_of(text)} — {'undergraduate' if stage == 'ug' else 'postgraduate'}"
    return text[:1].upper() + text[1:]


# ------------------------------------------------- slides 15, 16, 18

def _protection(fs, review_on):
    cd = fs.get("client_data", {})
    inv = _investments(fs)
    policies = []
    for p in inv.get("lic_policies") or []:
        policies.append({
            "name": str(p.get("policy_name") or "LIC policy"),
            "start": str(_year_of(p.get("commencement_date")) or DASH),
            "premium": _rupees(p.get("annual_premium")),
            "maturity": _money(p.get("maturity_value")) if _number(p.get("maturity_value")) else DASH,
            "payout": DASH,
            "remarks": f"Linked to {p['linked_goal']}" if p.get("linked_goal") else "Endowment",
        })
    seen = set()
    for p in (inv.get("ulips") or []) + (inv.get("retirement_investments", {}).get("ulip") or []):
        key = (p.get("policy_name"), p.get("commencement_date"))
        if key in seen:
            continue
        seen.add(key)
        policies.append({
            "name": str(p.get("policy_name") or "ULIP"),
            "start": str(_year_of(p.get("commencement_date")) or DASH),
            "premium": _rupees(p.get("annual_premium")),
            "maturity": (f"{_money(p.get('maturity_value'))} in {p.get('maturity_year')}"
                         if _number(p.get("maturity_value")) else DASH),
            "payout": DASH,
            "remarks": "ULIP",
        })
    for p in cd.get("life_insurance") or []:
        policies.append({"name": str(p.get("company_name") or "Life cover"), "start": DASH, "premium": DASH,
                         "maturity": DASH, "payout": _money(p.get("coverage_value")), "remarks": "Life cover"})
    for p in cd.get("medical_insurance") or []:
        policies.append({"name": str(p.get("company_name") or "Health cover"), "start": DASH, "premium": DASH,
                         "maturity": DASH, "payout": _money(p.get("coverage_value")),
                         "remarks": f"Health · {p.get('policy_type') or 'Self'}"})

    term = fs.get("term_insurance_summary") or {}
    existing = _number(term.get("existing_cover"))
    needed = _number(term.get("total_term_required"))
    recommended = existing + max(0.0, needed)
    premium_total = sum(_number(p.get("annual_premium")) for p in (inv.get("lic_policies") or []))
    premium_total += sum(_number(p.get("annual_premium")) for p in {(
        q.get("policy_name"), q.get("commencement_date")): q for q in (inv.get("ulips") or [])}.values())

    values = {"policy": policies}
    if policies:
        values["policies_comment"] = (
            f"{_words(len(policies)).capitalize()} polic{'ies' if len(policies) != 1 else 'y'} on record"
            + (f", with {_rupees(premium_total)} a year in premiums." if premium_total
               else "; premiums are not recorded for the cover policies."))
    values["annual_premium_total"] = _rupees(premium_total) if premium_total else "Nil"
    values["life_cover_current"] = _money(existing) if existing else "Nil"
    values["cover_recommended"] = _money(recommended)
    ry = _retirement_year(fs, review_on)
    values["protection_intro"] = (
        f"Every goal in this plan assumes income continues to {ry}. Protection is what makes that assumption safe to rely on.")
    # Slide 18 -- the cover gap, from the workflow's term-cover calculation.
    values["cover_today_1_cover"] = _money(existing) if existing else "₹0"
    values["cover_rec_1_cover"] = _money(recommended)
    values["cover_gap"] = _money(max(0.0, needed))
    values["cover_gap_headline"] = (
        f"Life cover stands at {values['life_cover_current']}, against the {_money(recommended)} this family needs"
        if needed > 0 else f"Life cover of {_money(existing)} meets what this family needs")
    values["cover_gap_note"] = "short of the recommended cover" if needed > 0 else "no further cover needed"
    owed = _number(term.get("current_liabilities"))
    values["cover_debt_note"] = ("Outstanding loans come off the top before anything is left for the family."
                                 if owed else "There are no loans for the payout to clear first.")
    values["cover_gap_comment"] = (
        f"Cover is sized to replace {_money(term.get('pv_of_expenses'))} of the family's future expenses, "
        f"clear {_money(owed)} of loans and fund {_money(term.get('kids_education_cost'))} of education, "
        f"less {_money(term.get('liquidable_assets'))} of liquid assets already held.")
    return values, bool(term)


# ----------------------------------------------------- slide 20 FDs

def _fds(fs):
    rows = []
    for fd in _investments(fs).get("fixed_deposits") or []:
        rows.append({
            "issuer": str(fd.get("name_of_bank") or "Fixed deposit"),
            "amount": _rupees(fd.get("principal_amount")),
            "rate": _rate(fd.get("interest_rate")),
            "maturity": _month_year(fd.get("maturity_date")),
            "remarks": "",
        })
    values = {"fd": rows}
    if rows:
        values["fd_comment"] = (f"{_words(len(rows)).capitalize()} deposit{'s' if len(rows) != 1 else ''} held. "
                                "Deposits count towards the liquid pool the goals draw on.")
    return values


# ------------------------------------------------- slides 30, 31 education

def _education_stage(name):
    words = str(name or "").lower().replace("-", " ").split()
    if not words:
        return None
    if words[-1] == "pg" or any(w.startswith("postgrad") for w in words):
        return "pg"
    if words[-1] == "ug" or any(w.startswith(("undergrad", "graduation")) for w in words):
        return "ug"
    return None


def _child_of(name):
    words = str(name or "").strip().split()
    return " ".join(words[:-1]) if words and words[-1].lower() in ("ug", "pg") else str(name or "").strip()


def _rate_text(rate):
    """6% stays '6%'; 7.43% reads '7.4%'."""
    pct = rate * 100
    return f"{pct:.0f}%" if abs(pct - round(pct)) < 0.05 else f"{pct:.1f}%"


def _education_basis(info, target, year):
    """The line under a child's target: today's cost and the yearly growth
    that turns it into the target.

    The target is the advisor's figure when one was entered (Make plan asks
    for it), otherwise the fee table grown by the workflow. Today's cost is
    the fee table's figure for the course. The rate is whatever links the
    two, so the line always agrees with the number above it.
    """
    today, years = _number(info.get("current_cost")), info.get("years_to_goal")
    course = " · ".join(p for p in (info.get("stream"), info.get("destination"))
                        if p and str(p).upper() != "NA")
    course = f" · {course}" if course else ""
    if today and years and target:
        rate = _implied_rate(today, target, years)
        if rate >= 0:
            return f"{_money(today)} today{course}, at {_rate_text(rate)} a year over {years} years"
        return f"{_money(today)} today{course}; the target is below today's cost"
    if target and years:
        return f"Target for {year}{course}, {years} years away"
    return course.lstrip(" ·") or DASH


def _education(fs, stage):
    summary = {(e.get("name"), e.get("type")): e
               for e in fs.get("client_data", {}).get("education_planning_summary") or []}
    goals = sorted((g for g in _goals(fs) if _education_stage(g.get("goal_name")) == stage),
                   key=lambda g: g.get("target_year") or 0)[:2]
    rows, required, corpus, monthly = [], 0.0, 0.0, 0.0
    advisor_set = False  # True when Make plan's education targets set the amounts
    year = date.today().year
    for g in goals:
        child = _child_of(g.get("goal_name"))
        info = summary.get((child, stage.upper()), {})
        target = _number(g.get("target_corpus"))
        reached = _reached(g)
        row = {"child": child.upper(), "year": str(g.get("target_year") or ""), "target": _money(target),
               "corpus": _money(reached) if reached else "₹0"}
        row["basis"] = _education_basis(info, target, g.get("target_year"))
        advisor_set = advisor_set or bool(_number(info.get("user_target_corpus")))
        for k, (label, terms, value) in enumerate(_fit(_source_groups(g), 2 if stage == "ug" else 4), 1):
            row[f"src{k}_label"] = label + (f" · {terms}" if terms and stage == "pg" else "")
            row[f"src{k}_value"] = _money(value)
        if stage == "ug":
            row["note"] = _goal_status(g)
        rows.append(row)
        required += target
        corpus += reached
        monthly += _sip_today(g, year)
    values = {stage: rows}
    if rows:
        values[f"{stage}_combined_required"] = _money(required)
        values[f"{stage}_combined_corpus"] = _money(corpus)
        values[f"{stage}_monthly"] = _rupees(monthly) if monthly else "Nil"
        short = required - corpus
        values[f"{stage}_comment"] = (
            f"The plan builds {_money(corpus)} against {_money(required)} needed"
            + (f", {_money(short)} short. " if short > 1000 else ". ")
            + ("Targets are the amounts set for each course." if advisor_set
               else "Costs are inflated from today's fees to the year each course begins.")
        )
    return values


# ------------------------------------------------- slide 32 marriage

def _marriage(fs, review_on):
    goals = sorted((g for g in _goals(fs) if any(w in str(g.get("goal_name", "")).lower()
                                                 for w in ("marriage", "wedding"))),
                   key=lambda g: g.get("target_year") or 0)
    if not goals:
        return {}
    first = goals[0]
    year = first.get("target_year")
    required = sum(_number(g.get("target_corpus")) for g in goals)
    today = sum(_today_cost(fs, g) for g in goals)
    rate = _implied_rate(_today_cost(fs, first), _number(first.get("target_corpus")),
                         (year or review_on.year) - review_on.year)
    values = {
        "marriage_year": str(year or ""),
        "marriage_cost_today": _money(today) if today else DASH,
        "marriage_inflation": f"{rate:.0%}" if rate is not None else DASH,
        "marriage_years_left": str((year or review_on.year) - review_on.year),
        "marriage_future_cost": _money(required),
        "marriage_intro": ("One combined goal for the family. " + _goal_status(first)),
    }
    rows = []
    for g in goals:
        child = _child_of(re.sub(r"\s*(marriage|wedding)\s*$", "", str(g.get("goal_name", "")), flags=re.I))
        for label, terms, value in _source_groups(g):
            rows.append((label, " · ".join(p for p in (terms, child) if p), value))
    rows = _fit(rows, 3)
    for k in range(1, 4):
        label, terms, value = rows[k - 1] if k <= len(rows) else ("", "", None)
        values[f"marriage_src{k}_label"] = label
        values[f"marriage_src{k}_terms"] = terms
        values[f"marriage_src{k}_value"] = _money(value) if value else ""
    corpus = sum(_reached(g) for g in goals)
    margin = corpus - required
    values["marriage_corpus"] = _money(corpus)
    values["marriage_margin"] = (f"{_money(margin)} clear of the target" if margin >= 0
                                 else f"{_money(-margin)} short of the target")
    ry = _retirement_year(fs, review_on)
    values["marriage_contributions_end"] = str(ry or DASH)
    values["marriage_comment"] = (
        "Keep this corpus in a separate folio from the retirement pot, so it is not drawn down by accident.")
    return values


# ------------------------------------------------- slide 33 SSY

def _ssy(fs, review_on):
    """Slide 33, from the workflow's own SSY projection.

    plan_goals records ssy_projection: each Sukanya Samriddhi account valued
    at maturity with calculate_ssy_future_value(), the withdrawals the plan
    takes from it, and what is left at maturity. Nothing is recomputed here.
    The slide shows one account; with two daughters it shows the first.
    """
    projections = (fs.get("optimal_goal_allocation") or {}).get("ssy_projection") or []
    p = next((x for x in projections if x.get("maturity_value")), None)
    if not p:
        return {}
    annual, maturity = _number(p.get("annual_contribution")), _number(p.get("maturity_value"))
    opened = _year_of(p.get("opening_date"))
    paid_in = annual * 15  # the account takes deposits for its first 15 years
    first = str(p.get("child_name", "")).split(" ")[0]
    sentence = (f"Contributions of {_money(paid_in)} over fifteen years grow to {_money(maturity)}, "
                f"tax-free, by {p.get('maturity_year')}.")
    drawn = [w for w in p.get("withdrawals") or [] if _number(w.get("amount"))]
    if drawn:
        sentence += " " + "; ".join(
            f"{_money(w['amount'])} is drawn for {_display_goal_name(w.get('goal'))} in {w.get('year')}"
            for w in drawn) + "."
        left = _number(p.get("balance_at_maturity"))
        if left > 0:
            sentence += f" {_money(left)} remains at maturity."
    return {
        "ssy_start_date": _month_year(p.get("opening_date")),
        "ssy_annual_contribution": _rupees(annual),
        "ssy_rate": _rate(p.get("interest_rate")),
        "ssy_interest_to_date": DASH,  # contributions paid so far are not recorded
        "ssy_current_value": _money(p.get("current_value")),
        "ssy_end_date": str(p.get("maturity_year")),
        "ssy_contributions_end": str(p.get("contribution_end_year") or (opened + 15 if opened else DASH)),
        "ssy_interest_at_maturity": _money(max(0.0, maturity - paid_in)),
        "ssy_maturity_value": _money(maturity),
        "ssy_comment": f"For {first}: " + sentence[0].lower() + sentence[1:],
    }


# ------------------------------------------------- slides 34 - 42 retirement

def _retirement(fs, review_on):
    info = _client_info(fs)
    ry = _retirement_year(fs, review_on)
    years = int(info.get("years_to_retirement") or (ry - review_on.year if ry else 0))
    retire_age = _client(fs).get("retirement_age")
    life = info.get("life_expectancy") or 85
    required = _number((fs.get("required_retirement_corpus") or {}).get("recommendation", {}).get("recommended_corpus"))
    wealth = (fs.get("wealth_at_retirement") or {}).get("breakdown") or {}
    values = {"inflation_rate": "6%"}
    infl = _implied_rate(_number(info.get("current_annual_expenses")),
                         _number(info.get("future_annual_expenses_at_retirement")), years)
    if infl is not None:
        values["inflation_rate"] = f"{infl:.0%}"

    # Property counts only for the part not lived in.
    props = [d for e in fs.get("fixed_assets") or [] for k, d in e.items() if k == "real_estate_investment"]
    total_re = sum(_instrument_value(d) for d in props)
    let_out = sum(_instrument_value(d) for d in props if not d.get("is_self_occupied"))
    re_share = let_out / total_re if total_re else 0
    nps_year = None
    for d in (_investments(fs).get("retirement_investments") or {}).get("nps") or []:
        nps_year = _year_of(d.get("maturity_year")) or nps_year

    names = {"epf": "Provident Fund (EPF)", "ppf": "Public Provident Fund", "fixed_deposits": "Fixed deposits",
             "esop": "ESOPs", "rsu": "RSUs", "sip": "Retirement SIPs — MF", "freed_sip": "Freed EMIs, re-tagged",
             "lumpsum": "Lumpsum from liquid assets"}
    now, later = [], []
    for key, label in names.items():
        fv = _number((wealth.get(key) or {}).get("future_value"))
        if fv:
            now.append({"label": label, "value": _money(fv)})
    nps_fv = _number((wealth.get("nps") or {}).get("future_value"))
    if nps_fv:
        (later if nps_year and ry and nps_year > ry else now).append(
            {"label": "NPS — pays out from age 60" if nps_year and ry and nps_year > ry else "NPS", "value": _money(nps_fv)})
    re_fv = _number((wealth.get("real_estate") or {}).get("future_value")) * re_share
    if re_fv:
        later.append({"label": "Property, if sold", "value": _money(re_fv)})
    now.sort(key=lambda r: -_money_value(r["value"]))
    projected = sum(_money_value(r["value"]) for r in now + later)
    liquid = sum(_money_value(r["value"]) for r in now)

    expense_m = _number(info.get("future_annual_expenses_at_retirement")) / 12
    # The monthly income the client wants in retirement is an advisor input
    # (Make plan requires it); calculate_retirement_annuity checks it against
    # the corpus and records the result. Nothing here re-derives it.
    ra = fs.get("retirement_annuity") or {}
    if not _number(ra.get("desired_monthly_annuity")):
        raise ValueError("workflow_state has no retirement_annuity: run Make plan with the "
                         "desired monthly annuity set")
    annuity = _number(ra.get("desired_monthly_annuity"))
    rental = _number(ra.get("surplus_income_monthly"))
    values.update({
        "corpus_required": _money(required),
        "corpus_now": now[:7],
        "corpus_later": later[:2],
        "corpus_breakup": sorted(now + later, key=lambda r: -_money_value(r["value"])),
        "years_to_retirement": str(years),
        "retirement_monthly_expense": _money(expense_m),
        "rental_income": _money(rental) if rental else "Nil",
        "annuity_required": _money(annuity),
        "retirement_section_intro": (
            f"{_words(years).capitalize() if years <= 12 else years} years of accumulation against "
            f"{life - retire_age if isinstance(retire_age, int) else 'the'} years of drawdown. Each retirement asset is "
            f"projected to {ry} on its own terms, then consolidated."),
    })
    gap = required - projected
    values["retirement_summary_1"] = (
        f"On these assumptions, retiring at {retire_age} needs a corpus of about {_money(required)} to fund "
        f"{_money(annuity)} a month, inflated at {values['inflation_rate']}, to age {life}. "
        f"The plan builds {_money(projected)}, " + (f"leaving a gap of {_money(gap)}." if gap > 0
                                                     else f"{_money(-gap)} above the requirement."))
    values["retirement_summary_2"] = (
        f"{_money(liquid)} of it is liquid and drawable at {retire_age}; the rest arrives later or depends on a "
        "decision to sell. A core-and-satellite structure keeps the essential income in stable assets.")
    if ra.get("achievable"):
        values["annuity_comment"] = (
            f"The corpus can pay {_money(annuity)} a month from its yield alone, without drawing down "
            f"principal; it could support up to {_money(ra.get('max_monthly_annuity'))} a month.")
    else:
        values["annuity_comment"] = (
            f"From its yield alone the corpus pays {_money(ra.get('achievable_monthly_annuity'))} a month, "
            f"{_money(ra.get('shortfall_monthly'))} short of the {_money(annuity)} wanted; the gap has to come "
            "from drawing down principal or a larger corpus.")
    values["corpus_projected"] = _money(projected)
    return values


def _money_value(text):
    text = str(text or "").replace("₹", "").replace("+", "").replace(",", "").strip()
    try:
        if text.endswith("Cr"):
            return float(text[:-2]) * 1e7
        if text.endswith("L"):
            return float(text[:-1]) * 1e5
        return float(text)
    except ValueError:
        return 0.0


def _schemes(fs, review_on):
    """PF, PPF and NPS slides, each only when the client holds the scheme."""
    ret = _investments(fs).get("retirement_investments") or {}
    totals = (fs.get("retirement_schemes_fv") or {}).get("category_totals") or {}
    ry = _retirement_year(fs, review_on)
    client = _client(fs)
    years_left = (client.get("retirement_age") or 0) - (client.get("client_age") or 0)
    marks = [review_on.year, review_on.year + 5, review_on.year + 8, ry]
    values, include = {}, {}

    epf = ret.get("epf") or []
    if epf and totals.get("epf"):
        cur = sum(_number(e.get("current_value")) for e in epf)
        contrib = sum(_number(e.get("employee_employer_contribution_monthly")) for e in epf)
        r = _number(epf[0].get("interest_rate")) or 0.085
        for i, y in enumerate(marks, 1):
            fv = sum(epf_future_value(_number(e.get("current_value")), _number(e.get("employee_employer_contribution_monthly")),
                                      _number(e.get("interest_rate")) or r, min(y - review_on.year, years_left)) for e in epf)
            values[f"pf_bar_{i}_value"] = _money(fv)
            values[f"pf_bar_{i}_year"] = str(y)
        total = _number(totals["epf"])
        values.update({
            "pf_current_value": _money(cur), "pf_contribution": _rupees(contrib), "pf_step_up": "None assumed",
            "pf_roi": _rate(r), "pf_value_at_retirement": _money(total).replace(" Cr", " Crore"),
            "pf_value_note": "Tax-free at maturity",
            "pf_description": ("Employer and employee contribute together each month. Interest is declared annually, the "
                               "maturity is tax-free, and the balance compounds untouched until you leave employment."),
            "pf_recommendation": (f"Transfer, never withdraw, on a job change. Leave the balance to compound to {ry}, "
                                  "then move it into the debt core of the retirement portfolio."),
            "pf_comment": f"At {_rate(r)} the balance grows from {_money(cur)} to {_money(total)} by {ry} with no market risk.",
        })
        include["pf"] = True

    ppf = ret.get("ppf") or []
    if ppf and totals.get("ppf"):
        cur = sum(_number(p.get("current_value")) for p in ppf)
        annual = sum(_number(p.get("annual_contribution")) for p in ppf)
        r = _number(ppf[0].get("interest_rate")) or 0.071
        for i, y in enumerate(marks, 1):
            n = min(y - review_on.year, years_left)
            total = sum(ppf_future_value(_number(p.get("current_value")), _number(p.get("annual_contribution")),
                                         _number(p.get("interest_rate")) or r, n) for p in ppf)
            paid = min(total, cur + annual * n)
            values[f"ppf_bar_{i}_contrib"] = f"{paid / 1e5:.0f}"
            if i > 1:
                values[f"ppf_bar_{i}_interest"] = f"{(total - paid) / 1e5:.0f}"
            values[f"ppf_bar_{i}_total"] = f"₹{total / 1e5:.0f}L"
            values[f"ppf_bar_{i}_year"] = str(y)
        total = _number(totals["ppf"])
        values.update({
            "ppf_current_value": _money(cur), "ppf_contribution": _money(annual), "ppf_roi": _rate(r),
            "ppf_accounts": _words(len(ppf)).capitalize(),
            "ppf_value_at_retirement": f"₹{total / 1e5:.0f} Lakh" if total < 1e7 else _money(total),
            "ppf_value_note": f"Tax-free, and available in full from {ry}",
            "ppf_description": ("A voluntary, government-backed account with a fifteen-year term, extendable in "
                                "five-year blocks. Contributions, interest and maturity are all tax-free."),
            "ppf_recommendation": ("Contribute before the fifth of April each year so the full balance earns interest "
                                   "for the whole year. Extend rather than close at maturity."),
            "ppf_comment": f"At {_rate(r)} tax-free, {_money(annual)} a year takes the balance to {_money(total)} by {ry}.",
        })
        include["ppf"] = True

    nps = ret.get("nps") or []
    if nps and totals.get("nps"):
        cur = sum(_number(n.get("current_value")) for n in nps)
        monthly = sum(_number(n.get("monthly_contribution")) for n in nps)
        r = _number(nps[0].get("expected_corpus_growth_rate")) or 0.10
        mat = max(_year_of(n.get("maturity_year")) or ry for n in nps)
        at_ret = sum(nps_future_value(_number(n.get("current_value")), _number(n.get("monthly_contribution")),
                                      _number(n.get("expected_corpus_growth_rate")) or r, max(0, (ry - review_on.year) * 12))
                     for n in nps)
        total = _number(totals["nps"])
        gap = max(0, mat - ry)
        values.update({
            "nps_current_value": _money(cur), "nps_contribution": _rupees(monthly), "nps_roi": _rate(r),
            "nps_equity_allocation": DASH, "nps_maturity_year": str(mat), "nps_value_at_retirement": _money(at_ret),
            "nps_maturity_value": _money(total), "nps_gap_label": f"{_words(gap)} year{'s' if gap != 1 else ''} on",
            "nps_lumpsum": _money(total * 0.6), "nps_annuity": _money(total * 0.4),
            "nps_description": "Market-linked and low-cost, with an additional ₹50,000 tax deduction. It matures at 60.",
            "nps_recommendation": (f"Treat NPS as deferred corpus: counted in the lifetime total, but drawn as income "
                                   f"from {mat}. Shift towards the C and G tiers in the last few years before maturity."),
            "nps_comment": f"60% can be taken as a lump sum at maturity; 40% must buy an annuity.",
        })
        include["nps"] = True
    return values, include


# ------------------------------------------------- slides 27, 29 goals

NAMED_GOAL_WORDS = ("retirement", "marriage", "wedding")


def _misc_goals(fs, review_on):
    goals = sorted((g for g in _goals(fs)
                    if not _education_stage(g.get("goal_name"))
                    and not any(w in str(g.get("goal_name", "")).lower() for w in NAMED_GOAL_WORDS)),
                   key=lambda g: g.get("target_year") or 0)
    rows = []
    for g in goals:
        year = g.get("target_year")
        target = _number(g.get("target_corpus"))
        today = _today_cost(fs, g)
        years_left = (year or review_on.year) - review_on.year
        rate = _implied_rate(today, target, years_left)
        reached = _reached(g)
        sources = [{"label": label, "terms": terms, "value": _money(value)}
                   for label, terms, value in _fit(_source_groups(g), 4)]
        if not sources:
            sources = [{"label": "Not yet funded", "terms": "", "value": "₹0"}]
        # The two-row stencil draws both rows; a goal with one source leaves
        # the second blank rather than unfilled.
        while len(sources) < 2:
            sources.append({"label": "", "terms": "", "value": ""})
        margin = reached - target
        rows.append({
            "name": _display_goal_name(g.get("goal_name")), "year": str(year or ""),
            "cost_today": _money(today) if today else DASH,
            "inflation": f"{rate:.0%}" if rate is not None else DASH,
            "years_left": str(years_left), "future_cost": _money(target),
            "intro": _goal_status(g),
            "sources": sources, "corpus": _money(reached),
            "margin": (f"{_money(margin)} clear of the target" if margin >= 0 else f"{_money(-margin)} short of the target"),
            "redirect_label": f"From {year} the instalment redirects to", "redirect_to": "Retirement corpus",
            "comment": "Fund this goal only from its own instalments, so the education and retirement pots stay intact.",
        })
    return {"goals": rows}


# ------------------------------------------------------------------ entry

ASSUMPTIONS = {
    "assumption_equity_return": "12%",
    "assumption_debt_return": "7%",
    "assumption_education_inflation": "6%",
    "assumption_post_retirement_return": "8%",
}


def adapt(final_state, review_on=None, advisor=None):
    """Build the validated deck payload from a workflow final_state.

    review_on defaults to today. advisor is {name, designation, email}; the
    workflow does not carry it, so the caller supplies it (the contact slide
    falls back to the firm's name).
    """
    if not isinstance(final_state, dict) or not final_state:
        raise ValueError("final_state must be a non-empty dict")
    fs, review_on = final_state, review_on or date.today()

    values = _personal(fs, review_on)
    values.update(_cashflow(fs, review_on))
    values.update(_assets(fs))
    loans = _loans(fs, review_on)
    values["loan"] = loans
    values["loan_heading_suffix"] = ""  # each loan slide is titled with the loan's name
    values.update(_goals_section(fs, review_on))
    protection, has_term = _protection(fs, review_on)
    values.update(protection)
    values.update(_fds(fs))
    values.update(_education(fs, "ug"))
    values.update(_education(fs, "pg"))
    marriage = _marriage(fs, review_on)
    values.update(marriage)
    ssy = _ssy(fs, review_on)
    values.update(ssy)
    values.update(_retirement(fs, review_on))
    schemes, scheme_include = _schemes(fs, review_on)
    values.update(schemes)
    values.update(_misc_goals(fs, review_on))
    values.update(ASSUMPTIONS)
    values["action"] = []  # the workflow writes no action plan yet
    info = _client_info(fs)
    values["life_expectancy"] = str(info.get("life_expectancy") or 85)
    advisor = advisor or {}
    values["advisor_name"] = advisor.get("name") or "Armstrong Capital"
    values["advisor_designation"] = advisor.get("designation") or "Wealth Advisory"
    values["advisor_email"] = advisor.get("email") or DASH

    # Sections, as the previous builder decided them: present only with data.
    values["include"] = Include(
        home_loan=bool(loans),
        other_loan=len(loans) > 1,
        protection_detail=has_term,
        education=bool(values.get("ug") or values.get("pg")),
        marriage=bool(marriage),
        ssy=bool(ssy),
        **scheme_include,
    )
    return PlanValues(**values)
