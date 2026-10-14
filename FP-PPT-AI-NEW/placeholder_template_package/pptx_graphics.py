"""Redraw the client-data graphics of the Goal Based Planning deck.

Every chart, donut, gauge and sized bar is regenerated from the client's values,
so no sample figure survives into a client deck. Used by populate_pptx.py.
"""
import math
import re

from lxml import etree

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
SVG = "http://www.w3.org/2000/svg"
NS = {"a": A, "p": P, "c": C, "s": SVG}
EMU = 914400


# ------------------------------------------------------------- values

def money(text):
    """Rupees in a formatted amount: '₹1.47 Cr', '~₹21.0 L', '₹4,50,000', '25 Lakhs'."""
    if text is None:
        return 0.0
    m = re.search(r"([\d,]*\.?\d+)\s*(cr|crore|l\b|lakh|lakhs|k\b)?", str(text), re.I)
    if not m:
        return 0.0
    n = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    return n * {"cr": 1e7, "crore": 1e7, "l": 1e5, "lakh": 1e5, "lakhs": 1e5, "k": 1e3}.get(unit, 1)


def pct(text):
    m = re.search(r"(-?\d+\.?\d*)\s*%", str(text or ""))
    return float(m.group(1)) / 100 if m else 0.0


def year(text):
    m = re.search(r"(19|20)\d\d", str(text or ""))
    return int(m.group(0)) if m else None


def inr(n):
    """Indian digit grouping: 185300 -> '1,85,300'."""
    s = str(int(round(n)))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
    return f"{head},{tail}"


# ------------------------------------------------------------- xml helpers

def shapes(root):
    return {sp.find(".//p:cNvPr", NS).get("name"): sp
            for sp in root.iter(f"{{{P}}}sp", f"{{{P}}}cxnSp")}


def geom(sp):
    off, ext = sp.find(".//a:xfrm/a:off", NS), sp.find(".//a:xfrm/a:ext", NS)
    return off, ext


def set_x(sp, x_in, w_in=None):
    off, ext = geom(sp)
    off.set("x", str(int(x_in * EMU)))
    if w_in is not None:
        ext.set("cx", str(max(0, int(w_in * EMU))))


def get_xw(sp):
    off, ext = geom(sp)
    return int(off.get("x")) / EMU, int(ext.get("cx")) / EMU


def set_text(sp, text):
    ts = sp.findall(".//a:t", NS)
    if ts:
        ts[0].text = text
        for t in ts[1:]:
            t.text = ""


def set_fill(sp, rgb):
    clr = sp.find("./p:spPr/a:solidFill/a:srgbClr", NS)
    if clr is not None:
        clr.set("val", rgb)




def nice_step(top, ticks=3):
    raw = max(top, 1e-9) / ticks
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 3, 4, 5, 10):
        if m * mag >= raw:
            return m * mag
    return 10 * mag


def fmt_num(n):
    return f"{n:g}" if n == int(n) else f"{n:.1f}"


# ------------------------------------------------------------- graphics

def segmented_bar(sh, parts, x0, x1, gap=0.03, min_label=0.9):
    """parts: [(shape name, label shape name or None, fraction, label text)]."""
    total = sum(f for _, _, f, _ in parts) or 1
    live = [p for p in parts if p[2] > 0]
    width = x1 - x0 - gap * (len(live) - 1)
    x = x0
    for name, label, frac, text in parts:
        w = width * frac / total if frac > 0 else 0
        bar = sh[name]
        if label:
            lx, _ = get_xw(sh[label])
            bx, _ = get_xw(bar)
            pad = lx - bx
            set_x(sh[label], x + pad, max(0, w - pad))
            set_text(sh[label], text if w >= min_label else "")
        set_x(bar, x, w)
        if w > 0:
            x += w + gap


def arc_path(cx, cy, r, a0, a1):
    """SVG arc from angle a0 to a1 (radians, clockwise on screen)."""
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    large = 1 if a1 - a0 > math.pi else 0
    return f"M{x0:.2f},{y0:.2f} A{r:g},{r:g} 0 {large} 1 {x1:.2f},{y1:.2f}"


def as_arc(el, d):
    """Turn a dashed circle/path into a solid arc path; renderers vary on dashes."""
    el.tag = f"{{{SVG}}}path"
    for attr in ("cx", "cy", "r", "stroke-dasharray", "stroke-dashoffset"):
        el.attrib.pop(attr, None)
    el.set("d", d)
    style = el.get("style")
    if style:
        style = re.sub(r"stroke-dasharray:[^;]*;", "stroke-dasharray: none;", style)
        el.set("style", re.sub(r"stroke-dashoffset:[^;]*;", "stroke-dashoffset: 0px;", style))


def donut(svg, values, total_text, sort=False, gap=4):
    """Each circle is one category; arcs run clockwise from 12 o'clock
    (the group is rotated -90deg), largest first when sort is set."""
    circles = svg.findall(".//s:circle", NS)
    cx, cy, r = (float(circles[0].get(k)) for k in ("cx", "cy", "r"))
    circ = 2 * math.pi * r
    total = sum(values) or 1
    # Fewer values than the design drew: the surplus circles keep the sample
    # geometry unless they are explicitly emptied, which would leave the ring
    # showing segments the legend beside it does not list.
    for circle in circles[len(values):]:
        as_arc(circle, f"M{cx},{cy}")
    order = sorted(range(len(values)), key=lambda i: -values[i]) if sort else range(len(values))
    pos = 0.0
    for i in order:
        seg = circ * values[i] / total
        dash = max(seg - gap, 0)
        a0, a1 = pos / r, (pos + dash) / r
        as_arc(circles[i], arc_path(cx, cy, r, a0, a1) if dash > 0 else f"M{cx},{cy}")
        pos += seg
    svg.findall(".//s:text", NS)[-1].text = total_text


def bars_svg(svg, groups, y0, y_top, ticks=3):
    """Redraw an SVG column chart. groups: list of (rects, values, labels)."""
    top = max((sum(v) for _, v, _ in groups), default=1)
    step = nice_step(top, ticks)
    scale = (y0 - y_top) / (step * ticks)
    tick_texts = svg.findall("./s:g[@text-anchor='end']/s:text", NS)
    for k, t in enumerate(tick_texts):
        t.text = fmt_num(step * k)
    for rects, vals, _ in groups:
        y = y0
        for r, v in zip(rects, vals):
            h = v * scale
            y -= h
            r.set("y", f"{y:.1f}")
            r.set("height", f"{h:.1f}")
    return scale


def graphics(n, root, parts, v):
    """Redraw the client-data graphics on template slide n."""
    sh = shapes(root)
    if n == 3:
        # The bar shows where income goes apart from loan EMIs: expenses,
        # savings and what is left unallocated. EMIs keep their own card
        # above the bar, so their segment and legend entry are dropped.
        e, m, s = pct(v["expenses_pct"]), pct(v["emis_pct"]), pct(v["savings_pct"])
        segmented_bar(sh, [("Shape 19", "Text 20", e, v["expenses_pct"]),
                           ("Shape 21", "Text 22", 0.0, ""),
                           ("Shape 23", "Text 24", s, v["savings_pct"]),
                           ("Shape 25", None, max(0.0, 1 - e - m - s), "")], 1.0, 19.0)
        shift = get_xw(sh["Shape 30"])[0] - get_xw(sh["Shape 28"])[0]
        for name in ("Shape 28", "Text 29"):
            sh[name].getparent().remove(sh[name])
        for name in ("Shape 30", "Text 31", "Shape 32", "Text 33"):
            set_x(sh[name], get_xw(sh[name])[0] - shift)
    elif n == 5:
        # Ring segments follow the rows the slide is actually showing, so the
        # chart cannot disagree with the table beside it.
        values = [money(v.get(f"alloc_{i}_value")) for i in range(1, 10)]
        donut(parts["ppt/media/image7.svg"], [a for a in values if a],
              v["total_assets"], sort=True)
    elif n == 7:
        svg = parts["ppt/media/image9.svg"]
        score = min(max(pct(v["health_score"]), 0), 1)
        as_arc(svg.findall(".//s:path", NS)[1],
               arc_path(250, 250, 210, math.pi, math.pi * (1 + score)) if score else "M250,250")
        svg.findall(".//s:text", NS)[0].text = v["health_score"]
    elif n == 13:
        amounts = [money(v.get(f"sip_{i}_amount")) for i in range(1, 7)]
        colors = ["26306F", "141A45", "2F7D3A", "94BCE3", "5980A6", "B7B7BA"]  # slot legend colours
        order = sorted(range(6), key=lambda i: -amounts[i])
        total = sum(amounts) or 1
        bars = ["Shape 3", "Shape 5", "Shape 7", "Shape 9", "Shape 11", "Shape 12"]
        labels = ["Text 4", "Text 6", "Text 8", "Text 10", None, None]
        seg = []
        for k, i in enumerate(order):
            set_fill(sh[bars[k]], colors[i])
            share = round(100 * amounts[i] / total)
            seg.append((bars[k], labels[k], amounts[i], f"{share}%"))
        segmented_bar(sh, seg, 1.0, 19.0)
    elif n == 18:
        chart(parts["ppt/charts/chart1.xml"],
              [[money(v["cover_today_1_cover"]) / 1e7, money(v["cover_rec_1_cover"]) / 1e7]])
    elif n == 23:
        start, today = year(v["loan_1_start_year"]), year(v["review_year"])
        early, close = year(v["loan_1_new_closing_year"]), year(v["loan_1_closing_year"])
        x0, x1 = 2.08, 18.33
        X = lambda y: x0 + (x1 - x0) * (y - start) / max(close - start, 1)
        xt, xe = X(today), X(early)
        for bar in ("Shape 105", "Shape 110"):
            set_x(sh[bar], x0, xt - x0)
        set_x(sh["Shape 106"], xt, x1 - xt)
        set_x(sh["Shape 111"], xt, xe - xt)
        set_x(sh["Shape 114"], xe, x1 - xe)
        set_x(sh["Text 115"], xe, x1 - xe)
        set_x(sh["Text 107"], x0 + 0.2, xt - x0 - 0.3)
        set_x(sh["Text 112"], x0 + 0.2, xt - x0 - 0.3)
        set_x(sh["Text 108"], xt + 0.2, x1 - xt - 0.3)
        set_x(sh["Text 113"], xt + 0.2, max(xe - xt - 0.3, 3.0))
        set_x(sh["Shape 116"], xt - 0.015)
        set_x(sh["Text 117"], xt - get_xw(sh["Text 117"])[1] / 2)
        for tick, label, x in (("Shape 119", "Text 120", x0), ("Shape 121", "Text 122", xt),
                               ("Shape 123", "Text 124", xe), ("Shape 125", "Text 126", x1)):
            set_x(sh[tick], x)
            set_x(sh[label], x - get_xw(sh[label])[1] / 2)
    elif n == 24:
        bal, r, emi = money(v["loan_1_outstanding"]), pct(v["loan_1_rate"]) / 12, money(v["loan_1_emi"])
        y0 = year(v["review_year"])
        cats, interest, principal, totals = [], [], [], []
        for k in range(7):
            m = 24 * k
            b = bal * (1 + r) ** m - emi * ((1 + r) ** m - 1) / r if r else bal - emi * m
            i = max(b, 0) * r
            cats.append(str(y0 + 2 * k))
            live = b > 0
            interest.append(round(i / 1000, 1) if live else None)
            principal.append(round((emi - i) / 1000, 1) if live else None)
            totals.append(round(emi / 1000, 1) if live else None)
        chart(parts["ppt/charts/chart2.xml"], [interest, principal, totals], cats, top=emi / 1000)
    elif n == 25:
        chart(parts["ppt/charts/chart3.xml"],
              [[money(v["loan_1_interest_outstanding"]) / 1e5, money(v["loan_1_interest_after_prepay"]) / 1e5]],
              ["Continue as it is", f"Prepay {v['loan_1_prepay_short']} in {v['review_year']}"])
    elif n == 35:
        column_bars(sh, [(f"Google Shape;{b};p42", f"Google Shape;{l};p42", money(v[f"pf_bar_{i}_value"]))
                         for i, (b, l) in enumerate([(1284, 1283), (1287, 1286), (1290, 1289), (1293, 1292)], 1)],
                    base=8.66, tallest=3.29, gap=0.53)
    elif n == 36:
        ppf_stack(sh, v)
    elif n == 37:
        earmarked, retained = money(v["equity_earmarked_value"]), money(v["equity_retained_value"])
        segmented_bar(sh, [("Google Shape;1409;p45", "Google Shape;1410;p45", earmarked, v["equity_earmarked_value"]),
                           ("Google Shape;1411;p45", "Google Shape;1412;p45", retained,
                            f"{v['equity_retained_value']} retained for retirement")], 0.92, 10.73, min_label=0.6)
        # Captions sit under their own segment.
        for bar, captions in (("Google Shape;1409;p45", ["Google Shape;1413;p45", "Google Shape;1414;p45"]),
                              ("Google Shape;1411;p45", ["Google Shape;1415;p45"])):
            bx, bw = get_xw(sh[bar])
            for c in captions:
                if bw > 0:
                    set_x(sh[c], bx + 0.02)
                else:
                    sh[c].getparent().remove(sh[c])
    elif n == 38:
        column_bars(sh, [("Google Shape;1373;p44", "Google Shape;1372;p44", money(v["nps_value_at_retirement"])),
                         ("Google Shape;1376;p44", "Google Shape;1375;p44", money(v["nps_maturity_value"]))],
                    base=8.66, tallest=3.21, gap=0.60)
    elif n == 39:
        start = money(v["retirement_sip_today"])
        steps = [money(v.get(f"freed_{i}_amount")) for i in range(1, 5)]
        base, run = [0], start
        for s_ in steps:
            base.append(run)
            run += s_
        base.append(0)
        cats = [f"{v['review_year']} today"] + [
            f"{v.get(f'freed_{i}_year', '')} {v.get(f'freed_{i}_event', '').lower()}".strip() for i in range(1, 5)
        ] + [f"{v['retirement_sip_final_year']} onward"]
        final = money(v["retirement_sip_final"])
        labels = [v["retirement_sip_today"]] + [f"+{inr(s_)}" if s_ else "" for s_ in steps] + [v["retirement_sip_final"]]
        chart(parts["ppt/charts/chart4.xml"],
              [base, [None] + steps + [None], [None] * 6, [start, None, None, None, None, final],
               [round(final / 100)] * 6], cats, labels={4: labels}, top=max(final, run))
    elif n == 42:
        vals = [money(v.get(f"corpus_breakup_{i}_value")) for i in range(1, 9)]
        donut(parts["ppt/media/image32.svg"], vals, v["corpus_projected"])
        annuity_bars(parts["ppt/media/image33.svg"], v)
    elif n == 46:
        chart(parts["ppt/charts/chart5.xml"],
              [[money(v["corpus_projected"]) / 1e7, money(v["corpus_required"]) / 1e7,
                money(v["corpus_with_plan"]) / 1e7]])


def set_y(sp, y_in, h_in=None):
    off, ext = geom(sp)
    off.set("y", str(int(y_in * EMU)))
    if h_in is not None:
        ext.set("cy", str(max(0, int(h_in * EMU))))


def column_bars(sh, bars, base, tallest, gap, floor=0.30):
    """Column bars standing on one baseline, the largest drawn `tallest` high.
    bars: [(bar shape, value label shape, value)]; labels sit `gap` above."""
    top = max((val for _, _, val in bars), default=0) or 1
    for bar, label, val in bars:
        h = max(floor, tallest * val / top)
        set_y(sh[bar], base - h, h)
        set_y(sh[label], base - h - gap)


def ppf_stack(sh, v):
    """PPF balance as four stacked columns: contributions (grey) with the
    interest earned (navy) on top. Both are freeform shapes with one
    rectangle per column, so their paths are rebuilt on a shared frame."""
    grey, navy = sh["Google Shape;1335;p43"], sh["Google Shape;1336;p43"]
    base, height = 8.42, 2.90
    contrib = [float(money(v[f"ppf_bar_{i}_contrib"])) for i in range(1, 5)]
    interest = [0.0] + [float(money(v.get(f"ppf_bar_{i}_interest"))) for i in range(2, 5)]
    lefts, width = [0, 2375916, 4750308, 7124700], 1583436
    g_off, g_ext = geom(grey)
    cx, cy = int(g_ext.get("cx")), int(height * EMU)
    scale = cy / (max(c + t for c, t in zip(contrib, interest)) or 1)
    for sp in (grey, navy):
        off, ext = geom(sp)
        off.set("x", g_off.get("x"))
        off.set("y", str(int((base - height) * EMU)))
        ext.set("cx", str(cx))
        ext.set("cy", str(cy))
    def rebuild(sp, spans):
        path = sp.find(".//a:custGeom/a:pathLst/a:path", NS)
        for child in list(path):
            path.remove(child)
        path.set("w", str(cx))
        path.set("h", str(cy))
        for x0, y0, y1 in spans:
            pts = [(x0, y0), (x0 + width, y0), (x0 + width, y1), (x0, y1)]
            for k, (x, y) in enumerate(pts):
                step = etree.SubElement(path, f"{{{A}}}{'moveTo' if k == 0 else 'lnTo'}")
                etree.SubElement(step, f"{{{A}}}pt", x=str(int(x)), y=str(int(y)))
            etree.SubElement(path, f"{{{A}}}close")
    rebuild(grey, [(x, cy - c * scale, cy) for x, c in zip(lefts, contrib) if c > 0])
    rebuild(navy, [(x, cy - (c + t) * scale, cy - c * scale)
                   for x, c, t in zip(lefts, contrib, interest) if t > 0])
    # Labels: contributions centred in grey, interest centred in navy, totals above.
    k_in = scale / EMU
    for i in range(4):
        c, t = contrib[i], interest[i]
        lab = sh[f"Google Shape;{1338 + i};p43"]
        set_y(lab, base - c * k_in / 2 - 0.175)
        if c * k_in < 0.35:
            set_text(lab, "")
        if i:
            lab = sh[f"Google Shape;{1341 + i};p43"]
            set_y(lab, base - (c + t / 2) * k_in - 0.175)
            if t * k_in < 0.35:
                set_text(lab, "")
        set_y(sh[f"Google Shape;{1345 + i};p43"], base - (c + t) * k_in - 0.40)


def annuity_bars(svg, v):
    """Monthly annuity required every five years from retirement, inflated."""
    start, base, infl = year(v["retirement_year"]), money(v["annuity_required"]) / 1e5, pct(v["inflation_rate"])
    vals = [base * (1 + infl) ** (5 * k) for k in range(6)]
    rects = svg.findall(".//s:rect", NS)
    scale = bars_svg(svg, [([r], [val], None) for r, val in zip(rects, vals)], 340, 88)
    groups = svg.findall("./s:g[@text-anchor='middle']", NS)
    for t, val in zip(groups[0].findall("s:text", NS), vals):
        t.text = f"{val:.2f}"
        t.set("y", f"{340 - val * scale - 12:.1f}")
    for k, t in enumerate(groups[1].findall("s:text", NS)):
        t.text = str(start + 5 * k)


def chart(root, series, cats=None, labels=None, top=None):
    """Replace literal chart data. series[i] lists values (None = no point).

    Charts with a fixed axis maximum keep it at 1.25x the tallest column, as
    the design does; pass that column's height as top.
    """
    for idx, (ser, vals) in enumerate(zip(root.findall(".//c:ser", NS), series)):
        lit = ser.find("./c:val/c:numLit", NS)
        for p in lit.findall("c:pt", NS):
            lit.remove(p)
        lit.find("c:ptCount", NS).set("val", str(len(vals)))
        for i, val in enumerate(vals):
            if val is not None:
                pt = etree.SubElement(lit, f"{{{C}}}pt", idx=str(i))
                etree.SubElement(pt, f"{{{C}}}v").text = f"{val:g}"
        if cats is not None:
            slit = ser.find("./c:cat/c:strLit", NS)
            for p in slit.findall("c:pt", NS):
                slit.remove(p)
            slit.find("c:ptCount", NS).set("val", str(len(cats)))
            for i, cat in enumerate(cats):
                pt = etree.SubElement(slit, f"{{{C}}}pt", idx=str(i))
                etree.SubElement(pt, f"{{{C}}}v").text = cat
        if labels and idx in labels:
            for dl in ser.findall("./c:dLbls/c:dLbl", NS):
                i = int(dl.find("c:idx", NS).get("val"))
                t = dl.find(".//a:t", NS)
                if t is not None and i < len(labels[idx]):
                    t.text = labels[idx][i]
    mx = root.find(".//c:valAx/c:scaling/c:max", NS)
    if mx is not None and top:
        mx.set("val", f"{top * 1.25:g}")
