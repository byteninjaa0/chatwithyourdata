"""Formatting and derived figures for the Goal Based Planning PPTX deck.

Totals, shares and summary figures are
computed from the rows a client actually has, so a client without NPS gets a
total and an allocation split that agree with the rows left on the slide.
Anything the values file states explicitly wins: an advisor override is never
silently recomputed.

Raw numbers are formatted to match the slot they fill. The design writes money
two ways, "₹38,00,000" in detail tables and "₹3.64 Cr" / "₹44.2 L" in summaries,
so each token takes the style of its sample value in pptx_template_tokens.json.
"""
import re

from pptx_graphics import inr, money, pct, year

# The Current Assets slide is driven by whatever the client holds, not by a
# fixed list of categories. ASSETS gives the preferred reading order and the
# display name for the categories the design was drawn around; a category not
# named here still gets a row, ordered after these and labelled from its key.
# Nothing is ever dropped for being unrecognised -- that would understate the
# client's total assets and, through it, their net worth.
ASSETS = {
    "real_estate": "Real Estate",
    "mutual_funds": "Mutual Funds",
    "epf": "EPF",
    "fixed_deposits": "Fixed Deposits",
    "gold": "Gold & SGB",
    "ppf": "PPF",
    "nps": "NPS",
    "direct_equity": "Direct Equity",
    "ssy": "Sukanya Samriddhi",
    # Classes the design did not draw but clients do hold. Listed for their
    # display name and reading order; the slide renders them like any other.
    "bonds": "Bonds",
    "ncd_govt": "NCDs & Govt Securities",
    "pms_aif": "PMS & AIF",
    "reits": "REITs",
    "esops": "ESOPs",
    "ulip": "ULIP",
    "other_investments": "Other Investments",
}
# The liquidity bucket each category belongs to. An unlisted category falls to
# DEFAULT_BUCKET, so it still reaches the bucket totals on the next slide.
# Buckets follow the workflow's own classification (ASSET_CLASSIFICATION in
# Nodes/basic_calculations_nodes.py) so the deck splits assets the way the plan
# behind it does.
BUCKETS = {
    "fixed": ["real_estate", "bonds", "pms_aif", "esops", "ncd_govt"],
    "liquid": ["mutual_funds", "direct_equity", "fixed_deposits", "gold",
               "reits", "other_investments"],
    "retirement": ["epf", "ppf", "nps", "ssy", "ulip"],
}
DEFAULT_BUCKET = "liquid"
# Rows the design can physically show. Up to this many asset classes are named
# individually. Past it the slide would be a wall of slivers, so it falls back
# to the largest ALLOC_NAMED by value plus a single "Other" -- a summary reads
# better than eight two-percent rows, and the total is unchanged either way.
ALLOC_SLOTS = 9
ALLOC_NAMED = 5


def asset_label(key):
    """Display name for an asset category key."""
    return ASSETS.get(key) or str(key).replace("_", " ").title()


def asset_bucket(key):
    """Liquidity bucket for a category, defaulting rather than discarding."""
    for bucket, keys in BUCKETS.items():
        if key in keys:
            return bucket
    return DEFAULT_BUCKET


def is_included(entry):
    return not (isinstance(entry, dict) and entry.get("to_include") is False)


def fmt_like(n, sample):
    """Format rupees n the way the design writes this slot's sample value."""
    s = str(sample or "").strip()
    if re.fullmatch(r"₹[\d,]+", s):
        return "₹" + inr(n)
    if s.endswith("Cr"):
        if money(s) < 1e7 or n >= 1e7:  # "₹0.63 Cr": this slot is always in crore
            return f"₹{n / 1e7:.2f} Cr"
        return f"₹{n / 1e5:.1f} L"
    if s.endswith(" L"):
        return f"₹{n / 1e7:.2f} Cr" if n >= 1e7 else f"₹{n / 1e5:.1f} L"
    if s.endswith("%"):
        return f"{n:g}%"
    return f"{n:g}"


def apportion(amounts):
    """Whole-number percentages that sum to exactly 100 (largest remainder)."""
    total = sum(amounts.values())
    if not total:
        return {k: "0%" for k in amounts}
    exact = {k: 100 * v / total for k, v in amounts.items()}
    floors = {k: int(x) for k, x in exact.items()}
    short = 100 - sum(floors.values())
    for k in sorted(exact, key=lambda k: exact[k] - floors[k], reverse=True)[:short]:
        floors[k] += 1
    return {k: f"{v}%" for k, v in floors.items()}


def format_numbers(values, lists, samples):
    """Render raw numbers as house-style strings, per the slot they fill."""
    out = {}
    for k, v in values.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = fmt_like(v, samples.get(k, ""))
        else:
            out[k] = v if isinstance(v, (dict, list)) else str(v)
    fmt_lists = {}
    for prefix, items in lists.items():
        rows = []
        for item in items:
            row = {}
            for f, v in item.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool) and f != "to_include":
                    row[f] = fmt_like(v, samples.get(f"{prefix}_1_{f}", ""))
                else:
                    row[f] = v
            rows.append(row)
        fmt_lists[prefix] = rows
    return out, fmt_lists


def derive(values, lists, samples):
    """Fill every derivable token the values file leaves out."""
    out = dict(values)

    def put(key, computed):
        if computed not in (None, "") and key not in out:
            out[key] = computed

    def like(key, n):
        return fmt_like(n, samples.get(key, ""))

    # Dates
    if "review_date" in out:
        put("review_year", str(year(out["review_date"]) or ""))
        put("review_date_caps", out["review_date"].upper())
    ry, rety = year(out.get("review_year")), year(out.get("retirement_year"))
    if ry and rety:
        put("years_to_retirement", str(rety - ry))
    # The retirement asset slides project each asset to this year.
    put("asset_horizon_year", out.get("retirement_year"))

    # Education panels: one per child. The header names every child's year,
    # and a child funded from fewer sources than the panel draws leaves the
    # spare rows blank rather than unfilled.
    for prefix, sources in (("ug", 2), ("pg", 4)):
        children = lists.get(prefix) or []
        put(f"{prefix}_years", " AND ".join(str(c.get("year", "")) for c in children))
        for child in children:
            for i in range(1, sources + 1):
                child.setdefault(f"src{i}_label", "")
                child.setdefault(f"src{i}_value", "")

    # Assets: rows, shares, buckets. Excluded or absent categories are dropped.
    assets = values.get("assets")
    if isinstance(assets, dict):
        # Every category the client holds, whether or not the design named it.
        # A zero or to_include:false entry drops out; a positive one never does.
        kept = {}
        for key, entry in assets.items():
            if not is_included(entry):
                continue
            amount = money(entry.get("amount") if isinstance(entry, dict) else entry)
            if amount:
                kept[key] = amount

        # Known categories first in the design's reading order, then the rest
        # largest first, so an unfamiliar class lands in a sensible position.
        known = [k for k in ASSETS if k in kept]
        extra = sorted((k for k in kept if k not in ASSETS),
                       key=lambda k: -kept[k])
        ordered = known + extra

        # While the classes fit the slide they are all named. Past that, the
        # largest ALLOC_NAMED by value are named and everything else becomes a
        # single "Other" row -- the column still totals the client's real
        # assets, it just stops listing slivers.
        if len(ordered) > ALLOC_SLOTS:
            shown = sorted(ordered, key=lambda k: -kept[k])[:ALLOC_NAMED]
            shown = [k for k in ordered if k in set(shown)]  # back to reading order
            folded = [k for k in ordered if k not in set(shown)]
            rows = [(asset_label(k), kept[k]) for k in shown]
            rows.append(("Other", sum(kept[k] for k in folded)))
        else:
            rows = [(asset_label(k), kept[k]) for k in ordered]

        shares = apportion({label: amount for label, amount in rows})
        for index, (label, amount) in enumerate(rows, 1):
            put(f"alloc_{index}_label", label)
            put(f"alloc_{index}_value", like(f"alloc_{index}_value", amount))
            put(f"alloc_{index}_pct", shares[label])
        out["_assets_rows"] = len(rows)

        total = sum(kept.values())
        put("total_assets", like("total_assets", total))

        sums = {b: 0.0 for b in BUCKETS}
        for key, amount in kept.items():
            sums[asset_bucket(key)] += amount
        bshares = apportion(sums)
        for bucket, amount in sums.items():
            put(f"bucket_{bucket}_value",
                like(f"bucket_{bucket}_value", amount) if amount else "—")
            put(f"bucket_{bucket}_pct", bshares[bucket])

    # Loans: every loan counts toward liabilities and EMIs.
    loans = lists.get("loan", [])
    if "loan" in lists:
        owed = sum(money(l.get("outstanding")) for l in loans)
        emis = sum(money(l.get("emi")) for l in loans)
        put("total_liabilities", like("total_liabilities", owed) if owed else "Nil")
        put("monthly_emis", like("monthly_emis", emis) if emis else "Nil")
    if "total_assets" in out and "total_liabilities" in out:
        put("net_worth", like("net_worth", money(out["total_assets"]) - money(out["total_liabilities"])))

    # Table totals
    fd = lists.get("fd")
    if fd:
        amounts = [money(r.get("amount")) for r in fd]
        total = sum(amounts)
        put("fd_total", like("fd_total", total))
        put("fd_total_short", like("fd_total_short", total))
        if total:
            avg = sum(a * pct(r.get("rate")) for a, r in zip(amounts, fd)) / total
            put("fd_avg_rate", f"{avg * 100:.2f}%")
    ia = lists.get("ia")
    if ia:
        put("ia_total_current", like("ia_total_current", sum(money(r.get("current")) for r in ia)))
        put("ia_total_allocated", like("ia_total_allocated", sum(money(r.get("allocated")) for r in ia)))
        put("ia_total_monthly", like("ia_total_monthly", sum(money(r.get("monthly")) for r in ia)))
    sip = lists.get("sip")
    if sip:
        total = sum(money(r.get("amount")) for r in sip)
        put("monthly_savings", like("monthly_savings", total))
        put("monthly_savings_short", like("monthly_savings_short", total))
    policy = lists.get("policy")
    if policy:
        put("annual_premium_total", like("annual_premium_total", sum(money(r.get("premium")) for r in policy)))
    if lists.get("corpus_breakup"):
        put("corpus_projected", like("corpus_projected", sum(money(r.get("value")) for r in lists["corpus_breakup"])))
    if lists.get("corpus_now"):
        put("corpus_liquid_total", like("corpus_liquid_total", sum(money(r.get("value")) for r in lists["corpus_now"])))
    freed = lists.get("freed")
    if freed and "retirement_sip_today" in out:
        final = money(out["retirement_sip_today"]) + sum(money(r.get("amount")) for r in freed)
        put("retirement_sip_final", like("retirement_sip_final", final))
        put("retirement_sip_final_year", max((str(r.get("year", "")) for r in freed), default=""))

    # Roadmap: chronological, with horizons and first/last goal years.
    road = lists.get("roadmap")
    if road:
        if all(year(r.get("year")) for r in road):
            road.sort(key=lambda r: year(r["year"]))
        for r in road:
            if "horizon" not in r and ry and year(r.get("year")):
                r["horizon"] = f"{year(r['year']) - ry} YRS"
        put("first_goal_year", str(road[0].get("year", "")))
        put("last_goal_year", str(road[-1].get("year", "")))
    return out
