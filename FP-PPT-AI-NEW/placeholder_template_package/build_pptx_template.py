"""Build the placeholder PPTX template from the designed sample deck.

The source deck ("Goal Based Plan Presentation Template 11Sep'26.pptx") is a
fully populated 49-slide example for a fictional client. This script replaces
every client-specific value in it with a {{token}}, touching only the characters
of the value itself so each run keeps its original font, size and colour.

    python build_pptx_template.py                 # writes financial_plan_template.pptx
    python build_pptx_template.py --verify        # also round-trips the sample values

Outputs, next to this script:
    financial_plan_template.pptx   the placeholder deck
    pptx_template_tokens.json      every token, the slides using it, and the
                                   value it had in the sample deck

Each SPEC entry is (original paragraph text, replacement). The replacement may
mix literal text with tokens, e.g. "COST AT {{vacation_year}}"; the original must
match that shape, and only the token spans are rewritten. When the same original
text appears several times on a slide, list it once per occurrence, in document
order. Every entry must match, so a change to the source deck fails loudly.

Graphics that carry client figures but are not text (native charts, SVG charts,
shapes sized to a value) are listed in GRAPHICS and in the token manifest; they
still show the sample client's data and must be regenerated per client.
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

from lxml import etree

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "Goal Based Plan Presentation Template 11Sep'26.pptx"
OUT = HERE / "financial_plan_template.pptx"
MANIFEST = HERE / "pptx_template_tokens.json"

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS = {"a": A}
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
TOKEN = re.compile(r"\{\{([a-z0-9_]+)\}\}")
PAGE = re.compile(r"^\d{1,2}\s*/\s*\d{1,2}$")
PAGE_REPL = "{{page_no}} / {{page_total}}"
SHORT = 12  # figures (amounts, years, rates) up to this length never wrap

# Label boxes drawn to fit their sample text exactly, widened so a client's
# own wording stays on one line. (slide, tokens, width in inches). The slide 2
# goal names sit at x=11.70 with their year column starting at x=15.97, so
# 4.0in fills the space without reaching it.
WIDEN_RIGHT = [
    (2, ["summary_goal_1_name", "summary_goal_2_name", "summary_goal_3_name"], 4.0),
    # Education funding lines: "SIP ₹35,000 a month · equity MF" is longer than
    # the sample the box was drawn around, and wraps onto the row beneath. The
    # value sits at x=8.95 (left panel) and x=16.64 (right), so 6.5in of label
    # clears the sample text without reaching the figure.
    # The left panel's figures start at x=8.95 and the right panel's at 16.64,
    # so each side gets the width that reaches its own figure, not past it.
    (30, [f"ug_1_src{s}_label" for s in (1, 2)], 7.4),
    (30, [f"ug_2_src{s}_label" for s in (1, 2)], 6.0),
    (31, [f"pg_1_src{s}_label" for s in (1, 2, 3, 4)], 7.4),
    (31, [f"pg_2_src{s}_label" for s in (1, 2, 3, 4)], 6.0),
    # The line under each child's target ("₹12.8 L today · B.Tech · Domestic,
    # at 11.2% a year over 8 years") wraps at the drawn width and its second
    # line lands on the divider. Nothing sits to its right, so it takes the
    # card's width: panels start at x=1.26 / 10.47 and the cards end at
    # about 9.9 / 19.1, so 8.3in stays inside both.
    (30, ["ug_1_basis"], 8.3),
    (30, ["ug_2_basis"], 8.3),
    (31, ["pg_1_basis"], 8.3),
    (31, ["pg_2_basis"], 8.3),
    # Loan slide titles are the loan's name; the box was drawn around "Home
    # Loan" and wraps "Personal Loan". The logo starts at x=16.73, so 12in
    # from x~1.0 holds a long name ("Loan Against Property") on one line.
    (8, ["loan_1_name"], 12.0),
    (9, ["loan_2_name"], 12.0),
    # Marriage funding rows: the label sits 0.54in above its terms line, so a
    # wrapped label lands on top of it. The figures start at x=16.29, and the
    # rows begin at x=9.98, so 6.2in holds a full label clear of them.
    (32, [f"marriage_src{s}_label" for s in (1, 2, 3)], 6.2),
    (32, [f"marriage_src{s}_terms" for s in (1, 2, 3)], 6.2),
    (32, ["marriage_margin"], 6.2),
]

# Boxes whose alignment or geometry drifted from their neighbours in the
# designed deck, squared up so a column reads straight down.
# (slide, tokens, {x, width, align} in inches) -- omitted keys are left alone.
ALIGN_BOXES = [
    # The first goal row's year was left-aligned in a slightly different box
    # from the two beneath it, so its year sat out of line with theirs.
    (2, ["summary_goal_1_years"], {"x": 16.08, "width": 2.59, "align": "r"}),
    # Loan slides: each figure's box was drawn around its sample, left-aligned
    # in the loan-details column, so a client's figures start at different x
    # and their right edges wander. Every figure in a column now shares one
    # right-aligned box ending where the design's column ends (9.51 / 18.76).
] + [
    (n, [f"loan_{k}_{f}" for f in ("outstanding", "rate", "emi", "closing_year", "interest_outstanding")],
     {"x": 6.51, "width": 3.0, "align": "r"})
    for n, k in ((8, 1), (9, 2))
] + [
    (n, [f"loan_{k}_{f}" for f in ("prepay_amount", "emi_topup", "interest_saved", "new_closing_year", "years_saved")],
     {"x": 15.76, "width": 3.0, "align": "r"})
    for n, k in ((8, 1), (9, 2))
]

# Allocation donut, slot order. The designed palette drew all nine slices from
# three hue families -- two near-identical navies, three greens, three blues --
# so neighbouring slices read as the same colour. These keep the brand navy,
# green and blue in the first three (the largest holdings for most clients) and
# separate every remaining slice by at least 25 degrees of hue, with the grey
# set apart by lightness instead. old -> new, applied to the SVG ring and the
# legend swatches together so the two cannot drift apart.
DONUT_PALETTE = {
    "141a45": "141a45",  # navy   - unchanged, brand anchor
    "26306f": "c8862b",  # was a second navy   -> amber
    "2f7d3a": "2f7d3a",  # green  - unchanged, brand
    "5980a6": "7a4f9e",  # was a muted blue    -> purple
    "4a9c55": "1a7ab5",  # was a second green  -> blue
    "7bbd85": "58b0a8",  # was a third green   -> teal
    "1a7ab5": "b5495b",  # was a second blue   -> rose
    "94bce3": "6b8f2e",  # was a third blue    -> olive
    "b7b7ba": "b7b7ba",  # grey   - unchanged, the "Other" slice
}


def widen(p, extra=1.5):
    """Give a no-wrap right- or centre-aligned box room to grow on its left.

    A box that cannot wrap overflows to the right; widening it leftwards keeps
    a right-aligned figure's right edge (and a centred one's centre) in place.
    """
    ppr = p.find("a:pPr", NS)
    algn = ppr.get("algn") if ppr is not None else None
    xfrm = p.getparent().getparent().find("p:spPr/a:xfrm", {**NS, "p": P_NS})
    if xfrm is None:
        return
    off, ext = xfrm.find("a:off", NS), xfrm.find("a:ext", NS)
    x1 = (int(off.get("x")) + int(ext.get("cx"))) / 914400
    if algn in (None, "l") and ppr is not None and int(ext.get("cx")) <= 2 * 914400 and x1 > 17.5:
        # A narrow left-aligned figure sized to its text at the right of a card:
        # right-aligning it looks the same and lets longer text grow leftwards.
        ppr.set("algn", "r")
        algn = "r"
    if algn not in ("r", "ctr"):
        return
    shift = min(int(extra * 914400), int(off.get("x")))
    off.set("x", str(int(off.get("x")) - shift))
    ext.set("cx", str(int(ext.get("cx")) + (shift if algn == "r" else 2 * shift)))


def widen_right(xml_bytes, tokens, width_in):
    """Grow a left-aligned label box rightwards to a fixed width.

    Several label boxes were drawn to fit their sample text exactly, so a
    client's longer wording wraps to a second line and collides with the row
    beneath. Where there is clear space to the right, the box is widened to a
    width that holds any reasonable label on one line.
    """
    root = etree.fromstring(xml_bytes)
    wanted = {"{{%s}}" % t for t in tokens}
    for sp in root.iter(f"{{{P_NS}}}sp"):
        text = "".join(t.text or "" for t in sp.iter(f"{{{A}}}t"))
        if not any(w in text for w in wanted):
            continue
        xfrm = sp.find("p:spPr/a:xfrm", {**NS, "p": P_NS})
        if xfrm is None:
            continue
        ext = xfrm.find("a:ext", NS)
        if int(ext.get("cx")) < int(width_in * 914400):
            ext.set("cx", str(int(width_in * 914400)))
        body = sp.find("p:txBody/a:bodyPr", {**NS, "p": P_NS})
        if body is not None:
            # The box is now wide enough; let it clip rather than reflow if a
            # label ever exceeds even this.
            body.set("wrap", "square")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def recolour(data, palette, is_svg=False):
    """Remap colours in one pass.

    Several of the new colours are also old ones, so replacing them one at a
    time would re-map a colour that had already been changed. A single regex
    pass over every hex value avoids that.
    """
    text = data.decode("utf-8") if isinstance(data, bytes) else data
    lookup = {k.lower(): v for k, v in palette.items()}
    pattern = (r'(stroke="#)([0-9A-Fa-f]{6})(")' if is_svg
               else r'(srgbClr val=")([0-9A-Fa-f]{6})(")')

    def swap(m):
        new = lookup.get(m.group(2).lower())
        return m.group(1) + (new.upper() if not is_svg else new) + m.group(3) if new else m.group(0)

    out = re.sub(pattern, swap, text)
    return out.encode("utf-8") if isinstance(data, bytes) else out


def align_boxes(xml_bytes, tokens, spec):
    """Square a box up with its neighbours: position, width and alignment."""
    root = etree.fromstring(xml_bytes)
    wanted = {"{{%s}}" % t for t in tokens}
    for sp in root.iter(f"{{{P_NS}}}sp"):
        text = "".join(t.text or "" for t in sp.iter(f"{{{A}}}t"))
        if not any(w in text for w in wanted):
            continue
        xfrm = sp.find("p:spPr/a:xfrm", {**NS, "p": P_NS})
        if xfrm is not None:
            if "x" in spec:
                xfrm.find("a:off", NS).set("x", str(int(spec["x"] * 914400)))
            if "width" in spec:
                xfrm.find("a:ext", NS).set("cx", str(int(spec["width"] * 914400)))
        if "align" in spec:
            for p in sp.iter(f"{{{A}}}p"):
                ppr = p.find("a:pPr", NS)
                if ppr is None:
                    ppr = etree.SubElement(p, f"{{{A}}}pPr")
                    p.insert(0, ppr)
                ppr.set("algn", spec["align"])
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def rows(prefix, n, fields):
    """Tokens for a fixed-slot table, row-major: prefix_1_field, ..."""
    return [f"{{{{{prefix}_{i}_{f}}}}}" for i in range(1, n + 1) for f in fields]


SPEC = {
    1: [
        ("Mr. & Mrs. Rohan Iyer", "{{client_display_name}}"),
        ("September 2026", "{{review_date}}"),
    ],
    2: [
        ("Mr. Rohan Iyer", "{{client_name}}"),
        ("12 March 1981", "{{client_dob}}"),
        ("45 years", "{{client_age}} years"),
        ("55 years — 2036", "{{retirement_age}} years — {{retirement_year}}"),
        ("Mrs. Aditi Iyer", "{{spouse_name}}"),
        ("04 August 1983", "{{spouse_dob}}"),
        ("1. Aarav, 13       2. Isha, 8", "{{children_names_ages}}"),
        ("10 yrs to retirement", "{{years_to_retirement}} yrs to retirement"),
        ("Moderately aggressive", "{{risk_appetite}}"),
        ("Kid’s Education", "{{summary_goal_1_name}}"),
        ("2031 · 2035 · 2036", "{{summary_goal_1_years}}"),
        ("Retirement", "{{summary_goal_2_name}}"),
        ("2036", "{{summary_goal_2_years}}"),
        ("Vacation Planning", "{{summary_goal_3_name}}"),
        ("2029", "{{summary_goal_3_years}}"),
    ],
    3: [
        ("₹4,50,000", "{{gross_monthly_income}}"),
        ("₹1,50,000", "{{monthly_expenses}}"),
        ("33% of income", "{{expenses_pct}} of income"),
        ("₹58,300", "{{monthly_emis}}"),
        ("home and car", "{{emi_note}}"),
        ("₹2,20,000", "{{monthly_savings}}"),
        ("49% of income", "{{savings_pct}} of income"),
        ("33%", "{{expenses_pct}}"),
        ("13%", "{{emis_pct}}"),
        ("49%", "{{savings_pct}}"),
        ("Unallocated surplus ₹21,700", "Unallocated surplus {{monthly_surplus}}"),
        ("A 49% savings rate is the single strongest number in this plan — it is what makes retirement at 55 discussable at all. The unallocated ₹21,700 is deliberately left free; it absorbs a bad month before any goal has to be paused.", "{{cashflow_comment}}"),
    ],
    4: [
        ("₹3.64 Cr", "{{total_assets}}"),
        ("₹44.2 L", "{{total_liabilities}}"),
        ("₹3.20 Cr", "{{net_worth}}"),
    ],
    # Allocation rows are numbered slots, not named ones. The asset label is a
    # token like every other cell, so a client's own asset classes drive the
    # slide instead of the nine the design happened to draw. Row order here is
    # the design's reading order; pptx_derive fills it from what is held.
    5: [
        ("Real Estate", "{{alloc_1_label}}"),
        ("40%", "{{alloc_1_pct}}"), ("₹1.47 Cr", "{{alloc_1_value}}"),
        ("PPF", "{{alloc_2_label}}"),
        ("6%", "{{alloc_2_pct}}"), ("₹21.0 L", "{{alloc_2_value}}"),
        ("Mutual Funds", "{{alloc_3_label}}"),
        ("19%", "{{alloc_3_pct}}"), ("₹70.0 L", "{{alloc_3_value}}"),
        ("NPS", "{{alloc_4_label}}"),
        ("5%", "{{alloc_4_pct}}"), ("₹17.5 L", "{{alloc_4_value}}"),
        ("EPF", "{{alloc_5_label}}"),
        ("12%", "{{alloc_5_pct}}"), ("₹42.0 L", "{{alloc_5_value}}"),
        ("Direct Equity", "{{alloc_6_label}}"),
        ("4%", "{{alloc_6_pct}}"), ("₹14.0 L", "{{alloc_6_value}}"),
        ("Fixed Deposits", "{{alloc_7_label}}"),
        ("8%", "{{alloc_7_pct}}"), ("₹28.0 L", "{{alloc_7_value}}"),
        ("Sukanya Samriddhi", "{{alloc_8_label}}"),
        ("4%", "{{alloc_8_pct}}"), ("₹13.6 L", "{{alloc_8_value}}"),
        ("Gold & SGB", "{{alloc_9_label}}"),
        ("2%", "{{alloc_9_pct}}"), ("₹10.5 L", "{{alloc_9_value}}"),
        ("Two-fifths of the balance sheet sits in property, which cannot be drawn on goal by goal. The plan therefore funds every goal from the remaining ₹2.17 crore of financial assets and shifts new savings towards that side of the sheet.", "{{allocation_comment}}"),
    ],
    6: [
        ("40%", "{{bucket_fixed_pct}}"),
        ("34%", "{{bucket_liquid_pct}}"),
        ("26%", "{{bucket_retirement_pct}}"),
        ("~ ₹1.47 Cr", "~ {{bucket_fixed_value}}"),
        ("~ ₹1.23 Cr", "~ {{bucket_liquid_value}}"),
        ("EPF, PPF, NPS and SSY are pure long-lock assets. At ten years from retirement, a 26% allocation here is healthy and needs no addition beyond the statutory flows.", "{{bucket_retirement_desc}}"),
        ("~ ₹94.1 L", "~ {{bucket_retirement_value}}"),
    ],
    7: [
        ("Your current financial health is stable, with a score of 78%. The portfolio is adequately diversified, inflows are strong and every near-term goal is already funded. The score is held back by two things: 40% of the balance sheet is in property, and the plan currently depends on a single income.", "{{health_summary}}"),
        ("49%", "{{savings_pct}}"),
        ("12 months", "{{emergency_reserve}}"),
        ("13%", "{{emis_pct}}"),
        ("₹4.50 L", "{{gross_monthly_income_short}}"),
    ],
    8: [
        ("Home Loan", "{{loan_1_name}}"),
        ("₹38,00,000", "{{loan_1_outstanding}}"),
        ("8.40%", "{{loan_1_rate}}"),
        ("₹42,500", "{{loan_1_emi}}"),
        ("2039", "{{loan_1_closing_year}}"),
        ("₹27,40,000", "{{loan_1_interest_outstanding}}"),
        ("₹5,00,000", "{{loan_1_prepay_amount}}"),
        ("5% a year", "{{loan_1_emi_topup}}"),
        ("₹11,20,000", "{{loan_1_interest_saved}}"),
        ("2034", "{{loan_1_new_closing_year}}"),
        ("5 years", "{{loan_1_years_saved}}"),
        ("At 8.4% the loan costs more than the post-tax return on your deposits, so prepaying from the FD surplus is the better use of that money. Closing in 2034 also frees the EMI before retirement.", "{{loan_1_comment}}"),
    ],
    # Every loan after the first gets a copy of this slide, titled with the
    # loan's own name like the home-loan slide. The design's "— CAR" after
    # the section label becomes an empty-by-default suffix, so the heading
    # reads "LOAN DETAILS" without repeating the title.
    9: [
        ("Other Loan", "{{loan_2_name}}"),
        ("LOAN DETAILS — CAR", "LOAN DETAILS{{loan_heading_suffix}}"),
        ("₹6,20,000", "{{loan_2_outstanding}}"),
        ("9.20%", "{{loan_2_rate}}"),
        ("₹15,800", "{{loan_2_emi}}"),
        ("2030", "{{loan_2_closing_year}}"),
        ("₹1,10,000", "{{loan_2_interest_outstanding}}"),
        ("₹2,00,000", "{{loan_2_prepay_amount}}"),
        ("5% a year", "{{loan_2_emi_topup}}"),
        ("₹48,000", "{{loan_2_interest_saved}}"),
        ("2029", "{{loan_2_new_closing_year}}"),
        ("1 year", "{{loan_2_years_saved}}"),
        ("The car loan is the costliest debt on the sheet but the smallest. Clearing it from the monthly surplus rather than from the deposit book keeps the emergency reserve intact, and the freed EMI of ₹15,800 becomes part of the retirement SIP from 2029.", "{{loan_2_comment}}"),
    ],
    10: [
        ("Eight goals over eighteen years, mapped against the ₹3 lakh a month you already invest — and against every instalment that comes free along the way.", "{{goals_section_intro}}"),
        ("₹2.20 L", "{{monthly_savings_short}}"),
        ("Nil", "{{new_saving_required}}"),
    ],
    11: [
        ("2029", "{{roadmap_1_year}}"), ("International family vacation", "{{roadmap_1_label}}"),
        ("₹7.2 L at goal year", "{{roadmap_1_amount}}"), ("3 YRS", "{{roadmap_1_horizon}}"),
        ("2031", "{{roadmap_2_year}}"), ("Aarav — undergraduate", "{{roadmap_2_label}}"),
        ("₹40 L at goal year", "{{roadmap_2_amount}}"), ("5 YRS", "{{roadmap_2_horizon}}"),
        ("2035", "{{roadmap_3_year}}"), ("Aarav — postgraduate", "{{roadmap_3_label}}"),
        ("₹94 L at goal year", "{{roadmap_3_amount}}"), ("9 YRS", "{{roadmap_3_horizon}}"),
        ("2036", "{{roadmap_4_year}}"), ("Retirement at 55 · Isha’s undergraduate", "{{roadmap_4_label}}"),
        ("₹6.25 Cr corpus required", "{{roadmap_4_amount}}"), ("10 YRS", "{{roadmap_4_horizon}}"),
        ("2040", "{{roadmap_5_year}}"), ("Isha — postgraduate · SSY matures", "{{roadmap_5_label}}"),
        ("₹66.5 L from SSY", "{{roadmap_5_amount}}"), ("14 YRS", "{{roadmap_5_horizon}}"),
    ],
    12: list(zip(
        ["Mutual Funds — Equity", "₹52.0 L", "₹52.0 L", "₹77,000", "Education — UG 2031, PG 2035",
         "Mutual Funds — Hybrid", "₹18.0 L", "₹18.0 L", "₹35,000", "Vacation 2029 · Renovation 2031",
         "Mutual Funds — Retirement", "—", "—", "₹30,000", "Retirement 2036 — new SIP",
         "Direct Equity", "₹14.0 L", "₹14.0 L", "—", "Retirement 2036",
         "Fixed Deposits", "₹28.0 L", "₹18.0 L", "—", "Emergency reserve · ₹10 L to reallocate",
         "Gold & SGB", "₹10.5 L", "₹10.5 L", "₹6,000", "Marriage 2044",
         "Sukanya Samriddhi", "₹13.6 L", "₹13.6 L", "₹12,500", "Isha — education 2036, marriage 2044",
         "EPF · PPF · NPS", "₹80.5 L", "₹80.5 L", "₹59,500", "Retirement 2036 · NPS from 2041"],
        rows("ia", 8, ["asset", "current", "allocated", "monthly", "goals"]),
    )) + [
        ("₹2.17 Cr", "{{ia_total_current}}"),
        ("₹2.07 Cr", "{{ia_total_allocated}}"),
        # The table's own monthly total: the sum of its rows, which include
        # SSY/EPF contributions and existing SIPs, not just the goal SIPs that
        # monthly_savings (the cash-flow and SIP slides) counts.
        ("₹2,20,000", "{{ia_total_monthly}}"),
        ("Of the ₹2.20 lakh committed each month, the ₹30,000 tagged to retirement is funded by the FD reallocation rather than by fresh saving. Property is excluded here because it cannot be drawn on goal by goal.", "{{investment_allocation_comment}}"),
    ],
    13: [
        ("SIP Allocation — ₹2,20,000 a Month", "SIP Allocation — {{monthly_savings}} a Month"),
        ("35%", "{{sip_bar_1_pct}}"), ("27%", "{{sip_bar_2_pct}}"),
        ("16%", "{{sip_bar_3_pct}}"), ("14%", "{{sip_bar_4_pct}}"),
    ] + list(zip(
        ["Education — UG 2031, PG 2035", "₹77,000", "Retirement 2036 — new SIP", "₹30,000",
         "EPF · PPF · NPS — statutory", "₹59,500", "Sukanya Samriddhi — Isha", "₹12,500",
         "Vacation 2029 · Renovation 2031", "₹35,000", "Marriage 2044", "₹6,000"],
        rows("sip", 6, ["label", "amount"]),
    )) + [
        ("Two-thirds of the monthly commitment funds goals inside the next ten years, which is why only ₹30,000 currently reaches retirement. The redirection plan corrects that from 2029 onwards without raising the total.", "{{sip_comment}}"),
    ],
    14: list(zip(
        ["2029", "Car loan closes", "₹15,800", "2031", "Renovation funded", "₹20,000",
         "2034", "Home loan closes", "₹42,500", "2035", "Education funded", "₹77,000"],
        rows("freed", 4, ["year", "event", "amount"]),
    )) + [
        ("₹30,000", "{{retirement_sip_today}}"),
        ("RETIREMENT SIP FROM 2035", "RETIREMENT SIP FROM {{retirement_sip_final_year}}"),
        ("₹1,85,300", "{{retirement_sip_final}}"),
        ("Nil", "{{new_saving_required}}"),
        ("Each instalment is re-tagged the month it is freed rather than absorbed into spending. This is what lifts the retirement contribution six-fold in the last two years before 2036, and it is the cheapest ₹0.75 crore available to the plan.", "{{freed_cashflow_comment}}"),
    ],
    15: [
        ("Every goal in this plan assumes ten more years of income. Protection is what makes that assumption safe to rely on.", "{{protection_intro}}"),
        ("₹5 Cr", "{{cover_recommended}}"),
        ("₹1.5 Cr", "{{life_cover_current}}"),
        ("₹1.35 L", "{{annual_premium_total}}"),
    ],
    16: list(zip(
        ["Term Plan — Self", "Jun 2019", "₹24,800", "₹1.5 Cr cover to 2044", "—", "Raise towards ₹5 Cr — cover is 4.2× annual income",
         "Term Plan — Spouse", "Mar 2021", "₹14,200", "₹75 L cover to 2046", "—", "Top up to ₹1 Cr when the second income restarts",
         "Family Floater Health", "Aug 2018", "₹38,500", "₹10 L, renews annually", "—", "Add a ₹25 L super top-up this year",
         "Endowment Policy", "Jan 2012", "₹51,000", "₹9.6 L in 2032", "—", "Effective return ~4.6%; hold to maturity, do not renew",
         "Personal Accident", "Nov 2022", "₹6,400", "₹50 L cover", "—", "Adequate; no change"],
        rows("policy", 5, ["name", "start", "premium", "maturity", "payout", "remarks"]),
    )) + [
        ("Annual premium is ₹1.35 lakh, of which ₹51,000 buys very little cover. Life cover is 4.2× annual income against a 10× benchmark, and ₹10 lakh of health cover for four is thin.", "{{policies_comment}}"),
    ],
    17: [
        ("₹1.5 Cr on Rohan and ₹75 L on Aditi, both in force.", "{{cover_term_status}}"),
        ("Not held; charges dilute cover and returns alike.", "{{cover_ulip_status}}"),
        ("₹9.6 L maturing 2032, returning about 4.6% a year.", "{{cover_endowment_status}}"),
        ("₹10 L shared across all four members, in force.", "{{cover_floater_status}}"),
        ("Gap. ₹25 L above the ₹10 L limit costs about ₹9,000 a year.", "{{cover_topup_status}}"),
        ("₹50 L on accidental death or disability, in force.", "{{cover_pa_status}}"),
        ("Gap. A ₹25 L rider pays a lump sum on diagnosis.", "{{cover_ci_status}}"),
        ("Add at renewal. Keeps every policy alive if income stops.", "{{cover_waiver_status}}"),
        ("Mixing cover with investment is what makes protection expensive. Keeping the three jobs separate — term for income, floater and top-up for health, riders for illness — buys far more cover for the same ₹1.35 lakh a year.", "{{cover_classification_comment}}"),
    ],
    18: [
        ("Life cover stands at 4.2 times income, against the ten times this family needs", "{{cover_gap_headline}}"),
        ("₹3.15 Cr", "{{cover_gap}}"),
        ("Enough to fund the family for roughly seventeen years.", "{{cover_gap_note}}"),
        ("₹44.2 L", "{{total_liabilities}}"),
        ("Home and car loans come off the top before anything is left.", "{{cover_debt_note}}"),
        ("2036", "{{retirement_year}}"),
        ("Cover is sized to what the family would have to replace, not to what feels affordable. Ten times income clears the loans, funds both children's education and leaves Aditi an income for the years the salary would have covered.", "{{cover_gap_comment}}"),
    ],
    19: [
        ("The same ₹1.35 lakh premium can buy 2.4 times the cover it buys today", "{{cover_suggestion_headline}}"),
        ("₹1.35 L a year buys 4.2× income", "{{cover_today_summary}}"),
    ] + list(zip(
        ["Term cover", "₹2.25 Cr", "₹39,000", "Health floater", "₹10 L", "₹38,500",
         "Endowment", "₹9.6 L at 2032", "₹51,000", "Personal accident", "₹50 L", "₹6,400"],
        rows("cover_today", 4, ["label", "cover", "premium"]),
    )) + [
        ("₹1.35 L a year", "{{cover_today_total}}"),
        ("₹1.35 L a year buys 10× income", "{{cover_rec_summary}}"),
    ] + list(zip(
        ["Term cover", "₹5.40 Cr", "₹81,000", "Health floater + top-up", "₹35 L", "₹47,500",
         "Endowment", "held to maturity, not renewed", "₹0", "Personal accident", "₹50 L", "₹6,400"],
        rows("cover_rec", 4, ["label", "cover", "premium"]),
    )) + [
        ("₹1.35 L a year", "{{cover_rec_total}}"),
        ("The endowment stays until it matures in 2032, so nothing already paid is lost. Its ₹51,000 renewal is simply not repeated: ₹42,000 of it buys the additional term cover and ₹9,000 buys the health top-up.", "{{cover_suggestion_comment}}"),
    ],
    20: list(zip(
        ["Public sector bank", "₹8,00,000", "7.10%", "Mar 2027", "Retain — core emergency reserve",
         "Private bank", "₹4,00,000", "7.40%", "Sep 2027", "Reallocate on maturity to the retirement portfolio",
         "Small finance bank", "₹5,00,000", "7.90%", "Jan 2028", "Retain — part of the emergency reserve",
         "Corporate deposit", "₹6,00,000", "8.20%", "Jul 2028", "AAA rated; carried into the retirement bucket",
         "Post office term deposit", "₹5,00,000", "7.50%", "Nov 2029", "Retain — part of the emergency reserve"],
        rows("fd", 5, ["issuer", "amount", "rate", "maturity", "remarks"]),
    )) + [
        ("₹28,00,000", "{{fd_total}}"),
        ("7.59% avg", "{{fd_avg_rate}} avg"),
        ("At ₹1.5 lakh of monthly expenses, ₹28 lakh is about nineteen months of cover; twelve is comfortable. After tax these deposits earn about 5.3% against 6% inflation, so roughly ₹10 lakh should move out of deposits and into the retirement portfolio as a lumpsum.", "{{fd_comment}}"),
    ],
    21: [
        ("The prepayment comes from idle deposits, not from the family's monthly budget", "{{prepay_funding_headline}}"),
        ("₹28.0 L", "{{fd_total_short}}"),
        ("Held in fixed deposits earning about 5.3% after tax — nineteen months of household expenses, where twelve is the agreed reserve.", "{{deposit_book_note}}"),
        ("₹18.0 L", "{{deposit_reserve_amount}}"),
        ("Twelve months of expenses at ₹1.5 L a month, untouched.", "{{deposit_reserve_note}}"),
        ("₹5.0 L", "{{deposit_prepay_amount}}"),
        ("Earns 8.4% risk-free by cancelling interest; saves ₹11.2 L.", "{{deposit_prepay_note}}"),
        ("₹5.0 L", "{{deposit_retirement_amount}}"),
        ("Grows at an expected 10-11% instead of 5.3% after tax.", "{{deposit_retirement_note}}"),
        ("The reserve stays fully intact at twelve months. Only the excess above it is put to work, so the family takes on no additional risk and gives up no liquidity it actually needs. The ₹2 lakh car-loan prepayment comes from monthly surplus, not from this pool.", "{{prepay_funding_comment}}"),
    ],
    22: [
        ("Seven years in, ₹36 lakh has left your account, and ₹38 lakh is still outstanding. This section shows why — and what a single ₹5 lakh decision changes.", "{{home_loan_section_intro}}"),
        ("₹11.2 L", "{{loan_1_interest_saved_short}}"),
        ("5 years", "{{loan_1_years_saved}}"),
    ],
    23: [
        ("Seven years in, the loan is only a quarter repaid — prepaying now ends it in 2034", "{{loan_life_headline}}"),
        ("₹35.7 L paid  ·  2019–2026", "{{loan_1_paid_to_date}} paid  ·  {{loan_1_start_year}}–{{review_year}}"),
        ("₹66.3 L still to pay, of which ₹27.4 L is interest", "{{loan_life_continue_note}}"),
        ("WITH ₹5 LAKH PREPAID IN 2026 AND A 5% EMI STEP-UP", "{{loan_life_prepay_label}}"),
        ("₹35.7 L paid  ·  2019–2026", "{{loan_1_paid_to_date}} paid  ·  {{loan_1_start_year}}–{{review_year}}"),
        ("₹16.2 L interest from here", "{{loan_1_interest_after_prepay}} interest from here"),
        ("5 years saved", "{{loan_1_years_saved}} saved"),
        ("TODAY · 2026", "TODAY · {{review_year}}"),
        ("2019 · loan taken", "{{loan_1_start_year}} · loan taken"),
        ("2026", "{{review_year}}"),
        ("2034 · loan free", "{{loan_1_new_closing_year}} · loan free"),
        ("2039", "{{loan_1_closing_year}}"),
        ("₹35.7 L", "{{loan_1_paid_to_date}}"),
        ("paid over seven years", "{{loan_1_paid_period}}"),
        ("₹11.2 L", "{{loan_1_interest_saved_short}}"),
        ("₹42,500", "{{loan_1_emi}}"),
        ("EMI freed five years early", "{{loan_1_emi_freed_note}}"),
        ("Loan start year, original principal and amount paid to date are derived from the stated EMI of ₹42,500, the 8.40% rate and the 2039 closing year; outstanding, interest and prepayment figures are as confirmed at review.", "{{loan_life_footnote}}"),
    ],
    24: [
        ("₹26,600 of today's ₹42,500 EMI is interest — only ₹15,900 reduces the loan", "{{emi_split_headline}}"),
        ("63%", "{{emi_interest_share}}"),
        ("Every month of delay costs ₹26,600 in interest alone.", "{{emi_interest_note}}"),
        ("2032", "{{emi_crossover_year}}"),
        ("Principal overtakes interest only six years from now.", "{{emi_crossover_note}}"),
        ("₹5 L", "{{loan_1_prepay_short}}"),
        ("prepaid moves the flip to 2029", "prepaid moves the flip to {{emi_crossover_year_prepaid}}"),
        ("Prepayment attacks principal directly, so the crossover arrives three years sooner.", "{{emi_prepay_note}}"),
        ("An EMI is not a fixed cost split evenly over the years. In the early years it is mostly rent on the borrowed money, which is why a prepayment made now is worth several times the same amount paid in 2034.", "{{emi_split_comment}}"),
    ],
    25: [
        ("₹5 lakh prepaid today removes ₹11.2 lakh of interest and five years of EMI", "{{prepay_impact_headline}}"),
        ("₹11.2 L", "{{loan_1_interest_saved_short}}"),
        ("a 224% return on the ₹5 lakh, tax-free", "{{prepay_return_note}}"),
        ("5 years", "{{loan_1_years_saved}}"),
        ("the loan ends in 2034, two years before retirement", "{{prepay_end_note}}"),
        ("₹42,500", "{{loan_1_emi}}"),
        ("a month freed from 2034", "a month freed from {{loan_1_new_closing_year}}"),
        ("The deposits behind the prepayment earn about 5.3% after tax while the loan charges 8.4%. Moving ₹5 lakh across that gap is the single highest-certainty return available in the plan, and it needs no market view.", "{{prepay_impact_comment}}"),
    ],
    26: [
        ("Eight goals, in the order the money is needed. Each slide states the target in the year it falls due, and the exact sources that meet it.", "{{goals_funding_intro}}"),
        ("2028", "{{first_goal_year}}"),
        ("2044", "{{last_goal_year}}"),
    ],
    # A goal slide. The design draws three of these -- vacation, the plot and
    # the build -- but they are one shape, so slide 27 is tokenised generically
    # and repeated once per goal the client actually holds. Slide 28 (the plot)
    # is the same shape and is never shipped; slide 29 has four funding rows,
    # and populate_pptx clones from whichever holds enough rows.
    27: [
        ("GOAL · 2028", "GOAL · {{goal_year}}"),
        ("International Family Vacation", "{{goal_name}}"),
        ("Cost today", "{{goal_cost_label}}"),
        ("₹9.00 L", "{{goal_cost_today}}"),
        ("Inflation assumed", "{{goal_inflation_label}}"),
        ("6%", "{{goal_inflation}}"),
        ("2", "{{goal_years_left}}"),
        ("REQUIRED IN 2028", "REQUIRED IN {{goal_year}}"),
        ("₹10.1 Lakh", "{{goal_future_cost}}"),
        ("Held in arbitrage and short-duration debt funds. At a two-year horizon the priority is that the money is intact in 2028, not that it grows.", "{{goal_intro}}"),
        ("SIP ₹20,000 a month", "{{goal_src1_label}}"),
        ("Arbitrage funds · 7% assumed · Sept 2026 – Mar 2028", "{{goal_src1_terms}}"),
        ("₹4.00 L", "{{goal_src1_value}}"),
        ("Existing deposit, re-tagged", "{{goal_src2_label}}"),
        ("₹5.50 L from the FD book · 7% · matures 2028", "{{goal_src2_terms}}"),
        ("₹6.30 L", "{{goal_src2_value}}"),
        ("Corpus available in 2028", "Corpus available in {{goal_year}}"),
        ("₹19,000 clear of the target", "{{goal_margin}}"),
        ("₹10.3 L", "{{goal_corpus}}"),
        ("From April 2028 the ₹20,000 SIP redirects to", "{{goal_redirect_label}}"),
        ("Home construction 2034", "{{goal_redirect_to}}"),
        ("Book the trip out of this corpus and nothing else. Funding a discretionary goal from the education or retirement pots is how a well-built plan quietly drifts.", "{{goal_comment}}"),
    ],
    # The same goal shape with four funding rows, used for a goal funded from
    # more sources than slide 27 can show.
    29: [
        ("GOAL · 2034", "GOAL · {{goal4_year}}"),
        ("Home Construction", "{{goal4_name}}"),
        ("Build cost today", "{{goal4_cost_label}}"),
        ("₹85.0 L", "{{goal4_cost_today}}"),
        ("Construction inflation", "{{goal4_inflation_label}}"),
        ("6%", "{{goal4_inflation}}"),
        ("8", "{{goal4_years_left}}"),
        ("REQUIRED IN 2034", "REQUIRED IN {{goal4_year}}"),
        ("₹1.35 Crore", "{{goal4_future_cost}}"),
        ("Built without a construction loan. The home loan closes in 2033 precisely so that no new debt is taken on a year later.", "{{goal4_intro}}"),
        ("SIP ₹30,000 a month", "{{goal4_src1_label}}"),
        ("Equity MF · 12% · 2026–2034", "{{goal4_src1_terms}}"),
        ("₹48.5 L", "{{goal4_src1_value}}"),
        ("Vacation and car SIPs redirected", "{{goal4_src2_label}}"),
        ("₹38,000 a month from 2028 and 2029", "{{goal4_src2_terms}}"),
        ("₹36.0 L", "{{goal4_src2_value}}"),
        ("Plot SIP redirected", "{{goal4_src3_label}}"),
        ("₹25,000 a month from 2030", "{{goal4_src3_terms}}"),
        ("₹15.3 L", "{{goal4_src3_value}}"),
        ("Lumpsum ₹25 L from mutual funds", "{{goal4_src4_label}}"),
        ("Existing holding · 12% to 2034", "{{goal4_src4_terms}}"),
        ("₹62.0 L", "{{goal4_src4_value}}"),
        ("Available in 2034", "Available in {{goal4_year}}"),
        ("₹26 L clear — the contingency on a build", "{{goal4_margin}}"),
        ("₹1.61 Cr", "{{goal4_corpus}}"),
        ("From April 2034 the combined ₹93,000 redirects to", "{{goal4_redirect_label}}"),
        ("Retirement corpus", "{{goal4_redirect_to}}"),
        ("Move this corpus out of equity in stages from 2032 — a third a year — so that a poor market in 2034 cannot delay the build. The ₹26 lakh surplus is deliberate: construction overruns are the norm, not the exception.", "{{goal4_comment}}"),
    ],
    # Undergraduate: one panel per child, each with its own target, the basis
    # that target is worked out from, the sources that fund it and the corpus
    # they reach. Sources are numbered so a child funded three ways fills the
    # rows a child funded two ways leaves empty.
    30: [
        ("GOAL · 2032 AND 2037", "GOAL · {{ug_years}}"),
        ("AARAV — 2032", "{{ug_1_child}} — {{ug_1_year}}"),
        ("₹44 Lakh", "{{ug_1_target}}"),
        ("₹25 L today, at 10% education inflation over 6 years", "{{ug_1_basis}}"),
        ("SIP ₹35,000 · equity MF · 12%", "{{ug_1_src1_label}}"),
        ("₹37 L", "{{ug_1_src1_value}}"),
        ("Lumpsum ₹5 L from mutual funds", "{{ug_1_src2_label}}"),
        ("₹10 L", "{{ug_1_src2_value}}"),
        ("Corpus by 2032", "Corpus by {{ug_1_year}}"),
        ("₹47 L", "{{ug_1_corpus}}"),
        ("₹35,000 redirects to Aarav’s PG from April 2032.", "{{ug_1_note}}"),
        ("IRA — 2037", "{{ug_2_child}} — {{ug_2_year}}"),
        ("₹71 Lakh", "{{ug_2_target}}"),
        ("₹25 L today, at 10% education inflation over 11 years", "{{ug_2_basis}}"),
        ("SIP ₹20,000 · equity MF · 12%", "{{ug_2_src1_label}}"),
        ("₹53 L", "{{ug_2_src1_value}}"),
        ("Lumpsum ₹8 L from mutual funds", "{{ug_2_src2_label}}"),
        ("₹28 L", "{{ug_2_src2_value}}"),
        ("Corpus by 2037", "Corpus by {{ug_2_year}}"),
        ("₹81 L", "{{ug_2_corpus}}"),
        ("₹20,000 redirects to Ira’s PG from April 2037.", "{{ug_2_note}}"),
        ("₹1.15 Cr", "{{ug_combined_required}}"),
        ("₹1.28 Cr", "{{ug_combined_corpus}}"),
        ("₹55,000", "{{ug_monthly}}"),
        ("If either course is taken abroad, add rupee depreciation of roughly 3% a year on top of the 10% — that raises Aarav’s requirement to about ₹53 lakh. We will re- test this at the 2029 review, when the subject choice is clearer.", "{{ug_comment}}"),
    ],
    # Postgraduate: same shape, but each child carries more funding sources --
    # the redirected undergraduate SIP, a lumpsum, and for the second child a
    # surplus carried over and an endowment maturity.
    31: [
        ("GOAL · 2036 AND 2041", "GOAL · {{pg_years}}"),
        ("AARAV — 2036", "{{pg_1_child}} — {{pg_1_year}}"),
        ("₹1.17 Crore", "{{pg_1_target}}"),
        ("₹45 L today, at 10% over 10 years — a two-year course abroad", "{{pg_1_basis}}"),
        ("SIP ₹22,000 · equity MF · 12%", "{{pg_1_src1_label}}"),
        ("₹51 L", "{{pg_1_src1_value}}"),
        ("UG SIP ₹35,000 redirected from 2032", "{{pg_1_src2_label}}"),
        ("₹21 L", "{{pg_1_src2_value}}"),
        ("Lumpsum ₹20 L from direct equity", "{{pg_1_src3_label}}"),
        ("₹62 L", "{{pg_1_src3_value}}"),
        ("Corpus by 2036", "Corpus by {{pg_1_year}}"),
        ("₹1.34 Cr", "{{pg_1_corpus}}"),
        ("IRA — 2041", "{{pg_2_child}} — {{pg_2_year}}"),
        ("₹1.88 Crore", "{{pg_2_target}}"),
        ("₹45 L today, at 10% over 15 years — four years after retirement", "{{pg_2_basis}}"),
        ("SIP ₹18,000 · equity MF · 12%", "{{pg_2_src1_label}}"),
        ("₹90 L", "{{pg_2_src1_value}}"),
        ("UG SIP ₹20,000 redirected 2037–2041", "{{pg_2_src2_label}}"),
        ("₹17 L", "{{pg_2_src2_value}}"),
        ("Surplus from Aarav’s PG corpus", "{{pg_2_src3_label}}"),
        ("₹28 L", "{{pg_2_src3_value}}"),
        ("Endowment maturity, reinvested", "{{pg_2_src4_label}}"),
        ("₹58 L", "{{pg_2_src4_value}}"),
        ("Corpus by 2041", "Corpus by {{pg_2_year}}"),
        ("₹1.93 Cr", "{{pg_2_corpus}}"),
        ("₹3.05 Cr", "{{pg_combined_required}}"),
        ("₹3.27 Cr", "{{pg_combined_corpus}}"),
        ("₹40,000", "{{pg_monthly}}"),
        ("Ira’s postgraduate year falls four years into retirement. It is funded from its own corpus, not from the retirement pot — that separation is deliberate and should be maintained even if markets are strong in 2037.", "{{pg_comment}}"),
    ],
    # Sukanya Samriddhi moved here when the goal block was restructured.
    33: [
        ("Apr 2019", "{{ssy_start_date}}"),
        ("₹1,50,000", "{{ssy_annual_contribution}}"),
        ("8.20%", "{{ssy_rate}}"),
        ("₹3.1 L", "{{ssy_interest_to_date}}"),
        ("₹13.6 L", "{{ssy_current_value}}"),
        ("Apr 2040", "{{ssy_end_date}}"),
        ("2034", "{{ssy_contributions_end}}"),
        ("8.20%", "{{ssy_rate}}"),
        ("₹44.0 L", "{{ssy_interest_at_maturity}}"),
        ("₹66.5 L", "{{ssy_maturity_value}}"),
        ("Total contributions of ₹22.5 lakh become ₹66.5 lakh, tax-free. Half of that funds Isha’s undergraduate course in 2036 through a partial withdrawal; the balance carries to 2040.", "{{ssy_comment}}"),
    ],
    # Children's marriage: one combined goal for the family rather than a
    # slide per child. Funding rows carry a label, the terms underneath it and
    # the value they reach; the corpus line states the margin over the target.
    32: [
        ("GOAL · 2044", "GOAL · {{marriage_year}}"),
        ("₹60.0 L", "{{marriage_cost_today}}"),
        ("6%", "{{marriage_inflation}}"),
        ("18", "{{marriage_years_left}}"),
        ("REQUIRED IN 2044", "REQUIRED IN {{marriage_year}}"),
        ("₹1.71 Crore", "{{marriage_future_cost}}"),
        ("A conditional goal. If the children marry later, or more modestly, the corpus returns to the retirement pool rather than being spent because it exists.", "{{marriage_intro}}"),
        ("SIP ₹22,000 a month", "{{marriage_src1_label}}"),
        ("Equity MF · 12% · 2026 to 2037", "{{marriage_src1_terms}}"),
        ("₹63 L", "{{marriage_src1_value}}"),
        ("Emergency SIP redirected", "{{marriage_src2_label}}"),
        ("₹25,000 a month from 2031 to 2037", "{{marriage_src2_terms}}"),
        ("₹26 L", "{{marriage_src2_value}}"),
        ("Compounding after retirement", "{{marriage_src3_label}}"),
        ("₹89 L left untouched · 11% · 2037 to 2044", "{{marriage_src3_terms}}"),
        ("+₹96 L", "{{marriage_src3_value}}"),
        ("Corpus in 2044", "Corpus in {{marriage_year}}"),
        ("₹14 L clear of the target", "{{marriage_margin}}"),
        ("₹1.85 Cr", "{{marriage_corpus}}"),
        ("April 2037", "{{marriage_contributions_end}}"),
        ("Keep this corpus in a separate folio from the retirement pot. Once withdrawals begin in 2037 it becomes very difficult to tell one pool from the other, and the marriage money is the first thing to be quietly consumed.", "{{marriage_comment}}"),
    ],
    34: [
        ("Retirement at 55", "Retirement at {{retirement_age}}"),
        ("Ten years of accumulation against thirty-five years of drawdown. Each retirement asset is projected through April 2037 on its own terms, then consolidated.", "{{retirement_section_intro}}"),
        ("₹6.25 Cr", "{{corpus_required}}"),
        ("₹5.50 Cr", "{{corpus_projected}}"),
    ],
    # Retirement asset slides, Sep-27 design: a four-figure header row, a
    # projection drawn as bars, a value-at-retirement panel, our recommendation
    # and an advisor comment. Bars are re-sized by pptx_graphics.
    35: [
        ("RETIREMENT ASSET · 2037", "RETIREMENT ASSET · {{asset_horizon_year}}"),
        ("Employer and employee contribute together each month. Interest is declared annually, the maturity is tax-free, and the balance compounds untouched until you leave employment.", "{{pf_description}}"),
        ("₹78 L", "{{pf_current_value}}"),
        ("₹38,000", "{{pf_contribution}}"),
        ("5% / 2 yrs", "{{pf_step_up}}"),
        ("8.10%", "{{pf_roi}}"),
        ("BALANCE TO APRIL 2037", "BALANCE TO APRIL {{asset_horizon_year}}"),
    ] + list(zip(
        ["₹78 L", "2026", "₹1.42 Cr", "2031", "₹2.10 Cr", "2034", "₹2.85 Cr", "2037"],
        rows("pf_bar", 4, ["value", "year"]),
    )) + [
        ("₹2.85 Crore", "{{pf_value_at_retirement}}"),
        ("20% of the total corpus, entirely tax-free", "{{pf_value_note}}"),
        ("Transfer, never withdraw, on a job change. Leave the balance to compound to 2037, then move it into the debt core of the retirement portfolio.", "{{pf_recommendation}}"),
        ("At 8.1% the PF balance roughly doubles every nine years with no market risk. If the declared rate falls below 7.5%, the case for the voluntary top-up weakens against equity over an eleven-year horizon.", "{{pf_comment}}"),
    ],
    36: [
        ("RETIREMENT ASSET · 2037", "RETIREMENT ASSET · {{asset_horizon_year}}"),
        ("A voluntary, government-backed account with a fifteen-year term, extendable in five-year blocks. Contributions, interest and maturity are all tax-free.", "{{ppf_description}}"),
        ("₹32 L", "{{ppf_current_value}}"),
        ("₹1.50 L", "{{ppf_contribution}}"),
        ("7.10%", "{{ppf_roi}}"),
        ("Two", "{{ppf_accounts}}"),
        ("BALANCE TO APRIL 2037 — CONTRIBUTIONS IN GREY, INTEREST EARNED IN NAVY", "BALANCE TO APRIL {{asset_horizon_year}} — CONTRIBUTIONS IN GREY, INTEREST EARNED IN NAVY"),
        ("₹92 Lakh", "{{ppf_value_at_retirement}}"),
        ("Tax-free, and available in full from 2037", "{{ppf_value_note}}"),
        ("Fund both accounts before the fifth of April each year so the full balance earns interest for the whole year. Extend rather than close at maturity.", "{{ppf_recommendation}}"),
        ("Contributing on the fifth of April rather than in March adds roughly ₹2.4 lakh over the eleven years, for no extra money. It is the cheapest improvement in this deck.", "{{ppf_comment}}"),
        # Chart labels, in the source's paragraph order: contributions (grey),
        # interest (navy, none in the first year), column totals, years.
        ("32", "{{ppf_bar_1_contrib}}"), ("39", "{{ppf_bar_2_contrib}}"),
        ("44", "{{ppf_bar_3_contrib}}"), ("49", "{{ppf_bar_4_contrib}}"),
        ("14", "{{ppf_bar_2_interest}}"), ("27", "{{ppf_bar_3_interest}}"), ("43", "{{ppf_bar_4_interest}}"),
        ("₹32L", "{{ppf_bar_1_total}}"), ("₹53L", "{{ppf_bar_2_total}}"),
        ("₹71L", "{{ppf_bar_3_total}}"), ("₹92L", "{{ppf_bar_4_total}}"),
        ("2026", "{{ppf_bar_1_year}}"), ("2031", "{{ppf_bar_2_year}}"),
        ("2034", "{{ppf_bar_3_year}}"), ("2037", "{{ppf_bar_4_year}}"),
    ],
    37: [
        ("RETIREMENT ASSET · 2037", "RETIREMENT ASSET · {{asset_horizon_year}}"),
        ("Eleven holdings built up over fifteen years. Four of them account for 58% of the book, and two sectors account for two- thirds of it.", "{{equity_description}}"),
        ("₹62 L", "{{equity_current_value}}"),
        ("11 stocks", "{{equity_holdings_count}} stocks"),
        ("58%", "{{equity_top_weight}}"),
        ("11%", "{{equity_roi}}"),
        ("HOW THE ₹62 LAKH IS USED", "HOW THE {{equity_current_value_caps}} IS USED"),
        ("₹20 L", "{{equity_earmarked_value}}"),
        ("₹42 L retained for retirement", "{{equity_retained_value}} retained for retirement"),
        ("Earmarked for Aarav’s PG in", "{{equity_earmarked_label}}"),
        ("2036", "{{equity_earmarked_year}}"),
        ("Consolidated into three funds", "{{equity_retained_note}}"),
        ("Retained book, 2026", "Retained book, {{equity_base_year}}"),
        ("₹42 L", "{{equity_retained_value}}"),
        ("Growth at 11% to 2037", "Growth at {{equity_roi}} to {{asset_horizon_year}}"),
        ("+₹92 L", "+{{equity_growth_value}}"),
        ("₹1.34 Cr", "{{equity_value_at_retirement}}"),
        ("₹1.34 Crore", "{{equity_value_at_retirement_long}}"),
        ("Move the seven smallest holdings into diversified funds over four financial years, using the ₹1.25 lakh annual exemption. Keep the four convictions you actively follow.", "{{equity_recommendation}}"),
        ("Individual stock selection needs continuous research, and a single-stock failure this close to retirement is difficult to recover from. Staging the exit over four years keeps the capital gains tax bill near zero.", "{{equity_comment}}"),
    ],
    38: [
        ("RETIREMENT ASSET · 2042", "RETIREMENT ASSET · {{nps_maturity_year}}"),
        ("Market-linked and low-cost, with an additional ₹50,000 deduction. It matures at 60, not at 55 — so it funds the second phase of retirement rather than the first.", "{{nps_description}}"),
        ("₹28 L", "{{nps_current_value}}"),
        ("₹20,000", "{{nps_contribution}}"),
        ("75E / 25C", "{{nps_equity_allocation}}"),
        ("10%", "{{nps_roi}}"),
        ("₹1.28 Cr", "{{nps_value_at_retirement}}"),
        ("2037 — you retire, contributions stop", "{{asset_horizon_year}} — you retire, contributions stop"),
        ("₹2.06 Cr", "{{nps_maturity_value}}"),
        ("2042 — maturity at 60, five years on", "{{nps_maturity_year}} — maturity at 60, {{nps_gap_label}}"),
        ("AT MATURITY IN 2042", "AT MATURITY IN {{nps_maturity_year}}"),
        ("₹1.24 Cr", "{{nps_lumpsum}}"),
        ("₹82 L", "{{nps_annuity}}"),
        ("Treat NPS as deferred corpus: counted in the lifetime total, but drawn as income from 2042, not available in 2037. Shift towards the C and G tiers from 2039 so the maturity value is not set by one bad market year.", "{{nps_recommendation}}"),
        ("The five-year gap between retiring at 55 and NPS maturing at 60 is bridged entirely by the mutual fund corpus. That is planned for on the withdrawal slides and needs no separate provision.", "{{nps_comment}}"),
    ],
    39: [
        ("Every instalment that ends is re-tagged, lifting the retirement SIP six-fold by 2035", "{{ladder_headline}}"),
        ("Nothing here asks the family to spend less. Each step is money already leaving the account as an EMI or a goal contribution; the discipline is simply to redirect it on the day it is freed rather than let it be absorbed.", "{{ladder_comment}}"),
    ],
    40: [
        ("Retirement Corpus — 2036", "Retirement Corpus — {{retirement_year}}"),
    ] + list(zip(
        ["Provident Fund (PF)", "₹1.75 Cr", "Public Provident Fund (PPF)", "₹0.63 Cr",
         "Retirement savings — MF", "₹0.70 Cr", "Financial assets — MF, direct equity", "₹0.44 Cr",
         "Fixed assets — FD, MLD, bonds", "₹0.35 Cr", "Education reallocation", "₹0.14 Cr",
         "Other assets — corporate FD", "₹0.13 Cr"],
        rows("corpus_now", 7, ["label", "value"]),
    )) + list(zip(
        ["NPS — pays out from age 60", "₹0.76 Cr", "Other asset class — second property, if monetised", "₹0.60 Cr"],
        rows("corpus_later", 2, ["label", "value"]),
    )) + [
        ("TOTAL WEALTH AT 2036", "TOTAL WEALTH AT {{retirement_year}}"),
        ("₹4.14 Cr", "{{corpus_liquid_total}}"),
        ("liquid and drawable at age 55", "liquid and drawable at age {{retirement_age}}"),
        ("₹5.50 Cr", "{{corpus_projected}}"),
    ],
    41: [
        ("2036", "{{retirement_year}}"),
        ("10 years", "{{years_to_retirement}} years"),
        ("₹2.69 L", "{{retirement_monthly_expense}}"),
        ("₹0.63 L", "{{rental_income}}"),
        ("₹2.06 L", "{{annuity_required}}"),
        ("~6%", "~{{inflation_rate}}"),
        ("₹6.25 Cr", "{{corpus_required}}"),
        ("₹5.50 Cr", "{{corpus_projected}}"),
        ("On these assumptions, retiring at 55 needs a corpus of about ₹6.25 crore to fund ₹2.06 lakh a month, inflated at 6%, to age 90. The plan currently builds ₹5.50 crore, leaving a gap of ₹0.75 crore.", "{{retirement_summary_1}}"),
        ("Three levers close it, and any two are sufficient: directing the ₹21,700 monthly surplus into the retirement SIP and deploying the ₹10 lakh FD reallocation as a lumpsum, which together add ₹0.81 crore by 2036; working to 57 instead of 55; or monetising the second property at retirement. Once funded, a core-and-satellite structure keeps the essential income in stable assets and leaves the satellite free for growth and legacy planning.", "{{retirement_summary_2}}"),
    ],
    42: list(zip(
        ["Provident Fund", "₹1.75 Cr", "Mutual Funds", "₹0.84 Cr", "NPS — from age 60", "₹0.76 Cr",
        "Public Provident Fund", "₹0.63 Cr", "Second property", "₹0.60 Cr", "Direct Equity", "₹0.44 Cr",
        "Fixed Deposits & Bonds", "₹0.35 Cr", "Corporate FD", "₹0.13 Cr"],
        rows("corpus_breakup", 8, ["label", "value"]),
    )) + [
        ("Figures in ₹ lakh per month, inflated at 6%.", "Figures in ₹ lakh per month, inflated at {{inflation_rate}}."),
        ("A flat withdrawal plan fails by the mid-2050s. The corpus has to keep a growth allocation through retirement, which is what the core-and-satellite structure is for.", "{{annuity_comment}}"),
    ],
    43: [
        ("Not yet drawn. With two properties and two minor children, a registered will is the priority action.", "{{legacy_will_note}}"),
        ("Refresh nominees on EPF, PPF, NPS, all folios and both term policies; three still name a parent.", "{{legacy_nominations_note}}"),
        ("₹1.35 crore matures in 2041. Deferred annuity for the second half of retirement or left as legacy.", "{{legacy_nps_note}}"),
        ("One consolidated statement of holdings, policies and access, shared with your spouse and reviewed yearly.", "{{legacy_records_note}}"),
        ("The surplus above the corpus requirement is what makes legacy planning relevant here rather than theoretical. None of these four items costs more than a day, and all four fail expensively if left undone.", "{{legacy_comment}}"),
    ],
    44: list(zip(
        ["Exit from FD or reallocate", "Move ₹10 lakh of the deposit book into the retirement portfolio as a lumpsum.",
        "Savings for retirement", "The ₹21,700 surplus as a SIP plus ₹10 lakh from the FD book adds ₹0.81 crore by 2036.",
        "Reduce your expense", "Every ₹10,000 a month trimmed today lowers the corpus required by about ₹42 lakh.",
        "Reconsider the home purchase", "A third property yields 2.6% and pushes real estate past 50%. Defer it.",
        "Build financial portfolio", "Bring property from 40% of assets towards 30% over the next five years.",
        "Home loan — prepay, don’t top up", "₹5 lakh prepaid with a 5% EMI step-up closes the loan in 2034, saving ₹11.2 lakh."],
        rows("action", 6, ["title", "desc"]),
        )),
    45: list(zip(
        ["Prepay the home loan", "₹5 lakh from the deposit book, with a 5% EMI step-up each year. The deposits earn 5.3% after tax; the loan costs 8.4%.", "₹11.2 L interest saved · closes 2034",
        "Rebuild the protection mix", "Hold the endowment to maturity and stop renewing it. The same premium budget buys term cover to ₹5 crore and a ₹25 lakh health top-up.", "Cover moves from 4.2× to 10× income",
        "Re-tag every freed EMI", "As each loan and goal closes, the instalment moves straight to the retirement SIP instead of into spending.", "₹30,000 becomes ₹1.85 L a month"],
        rows("suggestion", 3, ["title", "desc", "outcome"]),
    )) + [
        ("None of the three needs fresh money. Each one reuses cash the household already commits every month, which is why the plan can close the retirement gap without changing the family's standard of living.", "{{suggestions_comment}}"),
    ],
    46: [
        ("The three moves together turn a ₹0.75 crore retirement shortfall into a small surplus", "{{outcomes_headline}}"),
        ("Retirement corpus at 2036, ₹ crore", "Retirement corpus at {{retirement_year}}, ₹ crore"),
        ("Debt-free in 2034 instead of 2039, with ₹11.7 L of interest never paid across both loans.", "{{outcome_loan_note}}"),
        ("Life cover rises from 4.2× to 10× income and health cover from ₹10 L to ₹35 L, on the same premium.", "{{outcome_protection_note}}"),
        ("Retirement, both educations and the renovation are each funded by a named cash flow, not by whatever is left over.", "{{outcome_goals_note}}"),
        ("The ₹21,700 monthly surplus and the ₹10 lakh released from deposits add about ₹0.81 crore by 2036. That is what carries the corpus past the ₹6.25 crore the retirement income needs.", "{{outcomes_comment}}"),
    ],
    47: list(zip(
        ["The home loan ends in 2034, not 2039", "₹5 lakh of idle deposits removes ₹11.2 lakh of interest and five years of EMI.",
        "Cover trebles on the same premium", "₹1.35 lakh a year moves life cover from 4.2× to 10× income and health cover to ₹35 lakh.",
        "Freed EMIs go to work, not to spending", "The retirement SIP steps up from ₹30,000 to ₹1.85 lakh a month by 2035.",
        "The ₹0.75 crore retirement gap closes", "The corpus reaches ₹6.31 crore against ₹6.25 crore needed, with no new saving."],
        rows("takeaway", 4, ["title", "desc"]),
    )) + [
        ("Authorise the ₹5 lakh prepayment this quarter and submit the term-cover application before the next policy renewal.", "{{next_step}}"),
    ],
    48: [
        ("12%", "{{assumption_equity_return}}"),
        ("7%", "{{assumption_debt_return}}"),
        ("6%", "{{inflation_rate}}"),
        ("10%", "{{assumption_education_inflation}}"),
        ("8%", "{{assumption_post_retirement_return}}"),
        ("90 years", "{{life_expectancy}} years"),
    ],
    49: [
        ("Advisor Name", "{{advisor_name}}"),
        ("Designation", "{{advisor_designation}}"),
        ("Work Email", "{{advisor_email}}"),
        ("SEPTEMBER 2026", "{{review_date_caps}}"),
    ],
}

# Client figures that live outside text runs. They keep the sample client's data.
GRAPHICS = {
    3: "Cash-flow bar: segment widths are shapes sized to the expense / EMI / savings split.",
    5: "Allocation donut (SVG image7.svg) — ring segments and the '₹3.64 Cr' total are baked into the image.",
    6: "Bucket bar: segment widths are shapes sized to the 40 / 34 / 26 split.",
    7: "Health-score gauge (SVG image9.svg) — the '78%' score and the arc are baked into the image.",
    13: "SIP allocation bar: segment widths are shapes sized to the SIP split.",
    18: "Native chart (chart1): life cover in force vs recommended.",
    23: "Loan timeline: bar lengths and marker positions are shapes sized to the loan dates.",
    24: "Native chart: EMI split into interest and principal by year.",
    25: "Native chart: interest still payable, continue vs prepay.",
    35: "PF balance bars: shape heights sized to the projected balance.",
    36: "PPF stacked bars: custGeom paths sized to contributions and interest.",
    37: "Equity split bar: earmarked vs retained widths.",
    38: "NPS bars: value at retirement vs at maturity.",
    39: "Native chart: retirement SIP cash-flow ladder (waterfall).",
    42: "Corpus donut (SVG image32.svg) and annuity bar chart (SVG image33.svg).",
    46: "Native chart: retirement corpus — current path / required / with the plan.",
}


# ---------------------------------------------------------------- engine

def paragraph_runs(p):
    """Text-bearing <a:t> elements of a paragraph with their char offsets."""
    runs, pos = [], 0
    for t in p.iterfind(".//a:t", NS):
        s = t.text or ""
        runs.append([t, pos, pos + len(s)])
        pos += len(s)
    return runs


def para_text(p):
    return "".join(t.text or "" for t in p.iterfind(".//a:t", NS))


def replace_span(p, start, end, new):
    """Replace chars [start, end) of the paragraph text, keeping run formatting.

    The new text goes into the run where the span starts; later runs covered by
    the span lose only the covered characters.
    """
    first = True
    for t, rs, re_ in paragraph_runs(p):
        if re_ <= start or rs >= end:
            continue
        s = t.text or ""
        ls, le = max(start, rs) - rs, min(end, re_) - rs
        if first:
            t.text = s[:ls] + new + s[le:]
            first = False
        else:
            t.text = s[:ls] + s[le:]
    if first:
        raise ValueError("span not found in paragraph")


def pattern_for(repl):
    """Regex matching original text shaped like `repl`, one group per token."""
    parts, names, last = [], [], 0
    for m in TOKEN.finditer(repl):
        parts.append(re.escape(repl[last:m.start()]))
        parts.append("(.+?)")
        names.append(m.group(1))
        last = m.end()
    parts.append(re.escape(repl[last:]))
    return re.compile("".join(parts), re.S), names


def tokenise_slide(xml_bytes, spec, slide_no, samples, errors):
    root = etree.fromstring(xml_bytes)
    paras = [(p, para_text(p).strip()) for p in root.iter(f"{{{A}}}p")]
    seen = {}
    for orig, repl in spec:
        k = seen.get(orig, 0)
        seen[orig] = k + 1
        hits = [i for i, (_, t) in enumerate(paras) if t == orig]
        if k >= len(hits):
            errors.append(f"slide {slide_no}: {orig!r} occurrence {k + 1} not found ({len(hits)} present)")
            continue
        i = hits[k]
        p, text = paras[i]
        raw = para_text(p)
        lead = len(raw) - len(raw.lstrip())
        try:
            # Offsets are into the raw text; match against the stripped original.
            rx, names = pattern_for(repl)
            m = rx.fullmatch(text)
            if not m:
                raise ValueError(f"{text!r} does not fit the shape {repl!r}")
            for g in range(len(names), 0, -1):
                replace_span(p, lead + m.start(g), lead + m.end(g), "{{%s}}" % names[g - 1])
            if TOKEN.fullmatch(repl):
                for br in p.findall(".//a:br", NS):
                    br.getparent().remove(br)
            for name, value in zip(names, m.groups()):
                samples.setdefault(name, {}).setdefault(value, set()).add(slide_no)
            # Short figures (amounts, years, rates) were sized to the sample's exact
            # width; stop them wrapping when another client's figure is a hair wider.
            body = p.getparent().find("a:bodyPr", NS)
            texts = [t for t in (para_text(q).strip() for q in p.getparent().iterfind("a:p", NS)) if t]
            if len(text) <= SHORT and re.search(r"\d", text) and len(texts) == 1 and body is not None:
                body.set("wrap", "none")
                widen(p)
        except ValueError as e:
            errors.append(f"slide {slide_no}: {e}")
    for orig in {o for o, _ in spec}:
        extra = sum(1 for _, t in paras if t == orig) - seen[orig]
        if extra > 0:
            errors.append(f"slide {slide_no}: {orig!r} appears {extra} more time(s) than listed")
    # page numbers
    for p, text in paras:
        if PAGE.fullmatch(text):
            raw = para_text(p)
            lead = len(raw) - len(raw.lstrip())
            replace_span(p, lead, lead + len(text), PAGE_REPL)
            body = p.getparent().find("a:bodyPr", NS)
            if body is not None:  # "7 / 32" became "{{page_no}} / {{page_total}}"
                body.set("wrap", "none")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def slide_order(z):
    pres = z.read("ppt/presentation.xml").decode("utf8")
    rels = z.read("ppt/_rels/presentation.xml.rels").decode("utf8")
    targets = {}
    for rel in re.findall(r"<Relationship [^>]*/>", rels):
        rid = re.search(r'Id="([^"]+)"', rel).group(1)
        targets[rid] = re.search(r'Target="([^"]+)"', rel).group(1)
    return ["ppt/" + targets[r] for r in re.findall(r'<p:sldId [^>]*r:id="([^"]+)"', pres)]


def build(source, out):
    errors, samples = [], {}
    with zipfile.ZipFile(source) as z:
        order = slide_order(z)
        new = {}
        for n, name in enumerate(order, 1):
            new[name] = tokenise_slide(z.read(name), SPEC.get(n, []), n, samples, errors)
            for slide_no, tokens, width in WIDEN_RIGHT:
                if n == slide_no:
                    new[name] = widen_right(new[name], tokens, width)
            for slide_no, tokens, spec in ALIGN_BOXES:
                if n == slide_no:
                    new[name] = align_boxes(new[name], tokens, spec)
            if n == 5:
                # The allocation slide's legend swatches.
                new[name] = recolour(new[name], DONUT_PALETTE)
        # The ring itself, so it matches the swatches beside it.
        new["ppt/media/image7.svg"] = recolour(
            z.read("ppt/media/image7.svg"), DONUT_PALETTE, is_svg=True)
        if errors:
            sys.exit("Template build failed:\n  " + "\n  ".join(errors))
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as w:
            for info in z.infolist():
                data = new.get(info.filename, None)
                w.writestr(info, data if data is not None else z.read(info.filename))
    return order, samples


def write_manifest(samples, n_slides):
    tokens, conflicts = {}, []
    for name in sorted(samples):
        values = samples[name]
        if len(values) > 1:
            conflicts.append(f"{name}: " + " | ".join(f"{v!r} on {sorted(s)}" for v, s in values.items()))
        value, slides = next(iter(values.items()))
        tokens[name] = {"sample": value, "slides": sorted(set().union(*values.values()))}
    tokens["page_no"] = {"sample": "computed per slide", "slides": "all numbered slides"}
    tokens["page_total"] = {"sample": str(n_slides), "slides": "all numbered slides"}
    MANIFEST.write_text(json.dumps({
        "source": SOURCE.name,
        "slides": n_slides,
        "tokens": tokens,
        "graphics_not_tokenised": {str(k): v for k, v in GRAPHICS.items()},
    }, ensure_ascii=False, indent=2), encoding="utf8")
    return tokens, conflicts


def verify(source, out, tokens):
    """Fill the template with the sample values; text must equal the source."""
    values = {k: v["sample"] for k, v in tokens.items()}
    diffs = []
    with zipfile.ZipFile(source) as zs, zipfile.ZipFile(out) as zo:
        for n, name in enumerate(slide_order(zs), 1):
            a = [para_text(p) for p in etree.fromstring(zs.read(name)).iter(f"{{{A}}}p")]
            b = [para_text(p) for p in etree.fromstring(zo.read(name)).iter(f"{{{A}}}p")]
            for i, (x, y) in enumerate(zip(a, b)):
                if PAGE_REPL in y:
                    continue
                y = TOKEN.sub(lambda m: values[m.group(1)], y)
                if x.strip() != y.strip():
                    diffs.append(f"slide {n} para {i}: {x!r} != {y!r}")
            if len(a) != len(b):
                diffs.append(f"slide {n}: paragraph count {len(a)} != {len(b)}")
    return diffs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", type=Path, default=SOURCE)
    ap.add_argument("-o", "--out", type=Path, default=OUT)
    ap.add_argument("--verify", action="store_true", help="round-trip the sample values")
    args = ap.parse_args()

    order, samples = build(args.source, args.out)
    tokens, conflicts = write_manifest(samples, len(order))
    print(f"{args.out.name}: {len(order)} slides, {len(tokens)} tokens -> {MANIFEST.name}")
    if conflicts:
        print("Tokens with different sample values (check the mapping):")
        for c in conflicts:
            print("  " + c)
    if args.verify:
        diffs = verify(args.source, args.out, tokens)
        print("verify: OK" if not diffs else "verify FAILED:\n  " + "\n  ".join(diffs))
        if diffs or conflicts:
            sys.exit(1)


if __name__ == "__main__":
    main()
