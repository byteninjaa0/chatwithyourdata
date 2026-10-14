#!/usr/bin/env python3
"""Populate the 49-slide Goal Based Planning PPTX and export it to PDF.

The renderer half of the deck pipeline. Its input is the values file that
Financial_Planning/PPTX_Migration/adapter.py builds from a workflow
final_state; build a deck with Financial_Planning.PPTX_Migration.deck, which
runs both halves. Run directly only to debug a values file:

    python populate_pptx.py values.json -o out_dir [--no-pdf] [--allow-missing]

Writes <name>.pptx, <name>.pdf and client_values.json. The PDF is exported by
PowerPoint, so it matches the deck exactly; PowerPoint must be installed.

Behaviour:

* Lists hold any number of rows. Unused rows are removed from the slide. Rows
  beyond what a slide holds continue on a repeated "(cont.)" slide, with
  totals and commentary on the last page only (FDs, policies, investment
  allocation, action plan, goals road-map). Every loan after the first gets
  its own Other Loan slide. Lists drawn as a chart (SIP split, corpus
  break-up) fold their smallest rows into "Other" instead.
* "to_include": false removes a list row, an asset category, or (under
  "include") a whole section. Page numbers follow the slides actually kept.
* Totals, shares and summary figures are derived from the rows kept
  (pptx_derive.py); a value stated in the file always wins.
* Raw numbers are formatted in house style for the slot they fill.
* Every chart and graphic is redrawn from the client's values
  (pptx_graphics.py).
* A token with no value aborts the run and lists every one; a silently
  invented number in a client plan is worse than a failed run.
"""
import argparse
import json
import posixpath
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from lxml import etree

import pptx_layout as layout
from pptx_derive import derive, format_numbers, is_included
from pptx_derive import fmt_like
from pptx_graphics import A, NS, P, graphics, money

BASE = Path(__file__).resolve().parent
TEMPLATE = BASE / "financial_plan_template.pptx"
MANIFEST = BASE / "pptx_template_tokens.json"
TOKEN = re.compile(r"\{\{([a-z0-9_]+)\}\}")
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
SLIDE_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
NOTES_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"

# Slides that can be dropped with "include": {"<name>": false}, numbered as in
# the 49-slide Sep-27 source deck. Goal slides are not sections: they are one
# per entry in "goals", dropped with "to_include": false on the goal.
SECTIONS = {
    "home_loan": [8, 21, 22, 23, 24, 25],
    # Parts of a section a client deck may not have the data for: the
    # deposit-funded prepayment story and the loan-life charts, the cover
    # classification and the cover suggestions.
    "home_loan_detail": [21, 22, 23, 24, 25],
    "cover_classification": [17],
    "cover_suggestions": [19],
    "other_loan": [9],
    "protection_detail": [17, 18, 19],
    "education": [30, 31],
    "marriage": [32],
    "ssy": [33],
    "pf": [35],
    "ppf": [36],
    "direct_equity": [37],
    "nps": [38],
    "legacy": [43],
    "executive_summary": [45, 46, 47],
}

# How each list behaves when a client has more rows than its slide holds.
#   page:     repeat the slide as "(cont.)"; `final` tokens appear on the last page only
#   timeline: as page, and milestones are re-spaced along the road-map line
#   fold:     the list feeds a chart, so extra rows combine into one "Other" row
#   fixed:    the design has room for exactly this many; more is an error
LISTS = {
    "fd": {"slide": 20, "mode": "page", "final": ["fd_total", "fd_avg_rate", "fd_comment"]},
    "policy": {"slide": 16, "mode": "page", "final": ["policies_comment"]},
    "ia": {"slide": 12, "mode": "page", "final": ["ia_total_current", "investment_allocation_comment"]},
    "action": {"slide": 44, "mode": "page", "final": []},
    # timeline() clones a card style per milestone and spaces them along the
    # line, so the slide is not limited to the five the design drew. Cards are
    # 2.88in wide across a 14.40in span and alternate above and below, which
    # leaves same-side neighbours 2.88in apart at six -- still clear. Seven
    # starts to crowd, so that is where it pages.
    "roadmap": {"slide": 11, "mode": "timeline", "final": [], "cap": 6},
    "sip": {"slide": 13, "mode": "fold", "fold": ("label", "amount")},
    "corpus_breakup": {"slide": 42, "mode": "fold", "fold": ("label", "value")},
    "corpus_now": {"slide": 40, "mode": "fold", "fold": ("label", "value")},
    "corpus_later": {"slide": 40, "mode": "fold", "fold": ("label", "value")},
    "freed": {"slide": 14, "mode": "fixed"},
    "cover_today": {"slide": 19, "mode": "fixed"},
    "cover_rec": {"slide": 19, "mode": "fixed"},
    "suggestion": {"slide": 45, "mode": "fixed"},
    "takeaway": {"slide": 47, "mode": "fixed"},
    "summary_goal": {"slide": 2, "mode": "fixed"},
    # Education: one panel per child. An empty list drops the slide.
    "ug": {"slide": 30, "mode": "fixed", "drop_empty": True},
    "pg": {"slide": 31, "mode": "fixed", "drop_empty": True},
}
OTHER_LOAN = 9
# Goal slides. The design draws three, but they are one shape repeated, so the
# deck carries one per goal the client actually holds. A goal with more funding
# sources than the narrow stencil shows uses the wide one.
GOAL_SLIDE = 27
GOAL_SLIDE_WIDE = 29
# The design's plot goal: same shape as slide 27, which is cloned per goal, so
# the slide itself never ships.
STENCIL_ONLY = {28}
GOAL_ROWS = 2
LOAN_SLIDES = SECTIONS["home_loan"] + SECTIONS["other_loan"]
ASSET_SLIDE = 5
ASSET_TOKEN = re.compile(r"alloc_(\d+)_(?:label|pct|value)$")

# Values used only by a graphic, not by any slide text, keyed by template slide.
GRAPHIC_INPUTS = {7: ["health_score"], 18: ["cover_today_1_cover", "cover_rec_1_cover"],
                  46: ["corpus_with_plan"]}
# Tokens drawn by graphics() from other values; the values file may omit them.
DERIVED = {f"sip_bar_{i}_pct" for i in range(1, 5)}


# ------------------------------------------------------------- values

def load(path):
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"error: values file not found: {path}")
    except json.JSONDecodeError as exc:
        sys.exit(f"error: {path} is not valid JSON: {exc}")
    if not isinstance(raw, dict):
        sys.exit(f"error: {path} must contain a JSON object")
    include = raw.pop("include", {})
    unknown = set(include) - set(SECTIONS)
    if unknown:
        sys.exit(f"error: unknown include section(s) {sorted(unknown)}; known: {sorted(SECTIONS)}")
    lists = {k: [i for i in v if isinstance(i, dict) and is_included(i)]
             for k, v in raw.items() if isinstance(v, list)}
    unknown = set(lists) - set(LISTS) - {"loan", "goals"}
    if unknown:
        sys.exit(f"error: unknown list(s) {sorted(unknown)}; known: {sorted(set(LISTS) | {'loan'})}")
    values = {k: v for k, v in raw.items() if not isinstance(v, list)}
    return values, lists, include


def capacities(z, order):
    """{prefix: rows the template slide holds} for every numbered row list."""
    caps = {}
    for name in order:
        for t in set(TOKEN.findall(z.read(name).decode("utf8"))):
            m = re.fullmatch(r"([a-z0-9_]+?)_(\d+)_[a-z0-9_]+", t)
            if m:
                caps[m.group(1)] = max(caps.get(m.group(1), 0), int(m.group(2)))
    return caps


def fold(items, cap, fields, samples, prefix):
    """Keep cap-1 rows and combine the rest into one "Other" row."""
    if len(items) <= cap:
        return items
    label, amount = fields
    rest = items[cap - 1:]
    total = sum(money(r.get(amount)) for r in rest)
    # Write "Other" in the unit the client's own rows use ("₹0.06 Cr", not "₹6.0 L").
    style = next((str(r[amount]) for r in items if str(r.get(amount, "")).startswith("₹")),
                 samples.get(f"{prefix}_1_{amount}", "₹0.0 L"))
    if style.endswith("Cr"):
        style = "₹0.01 Cr"
    other = {label: "Other", amount: fmt_like(total, style)}
    return items[:cap - 1] + [other]


def row_tokens(prefix, items, start=1):
    return {f"{prefix}_{i}_{f}": str(v) for i, item in enumerate(items, start)
            for f, v in item.items() if f != "to_include"}


def goal_tokens(prefix, goal):
    """One goal's tokens, with its funding sources numbered."""
    out = {f"{prefix}_{f}": str(v) for f, v in goal.items()
           if f != "sources" and v is not None}
    for i, source in enumerate(goal.get("sources", []), 1):
        for f, v in source.items():
            if v is not None:
                out[f"{prefix}_src{i}_{f}"] = str(v)
    return out


# ------------------------------------------------------------- plan

def plan_slides(n_slides, lists, caps, include, samples, goals=None):
    """The deck as a list of pages: each is one template slide plus its rows."""
    dropped = {n for name, keep in include.items() if keep is False for n in SECTIONS[name]}
    dropped |= STENCIL_ONLY
    loans = lists.get("loan")
    if loans is not None and not loans:
        dropped |= set(LOAN_SLIDES)
    for prefix, spec in LISTS.items():
        if (spec["mode"] in ("page", "timeline") or spec.get("drop_empty"))                 and prefix in lists and not lists[prefix]:
            dropped.add(spec["slide"])  # an empty table is dropped, not rendered bare

    errors = []
    for prefix, spec in LISTS.items():
        items = lists.get(prefix)
        if items is None:
            continue
        cap = spec.get("cap") or caps.get(prefix)
        if not cap:
            # The slide holding this list carries no numbered tokens yet, so
            # there is nothing to fill or to overflow against.
            continue
        if spec["mode"] == "fold":
            lists[prefix] = fold(items, cap, spec["fold"], samples, prefix)
        elif spec["mode"] == "fixed" and len(items) > cap:
            errors.append(f"'{prefix}' has {len(items)} rows; slide {spec['slide']} holds {cap}")
    if errors:
        sys.exit("error: " + "\n       ".join(errors))

    by_slide = {}
    for prefix, spec in LISTS.items():
        by_slide.setdefault(spec["slide"], []).append(prefix)

    pages = []
    for n in range(1, n_slides + 1):
        page = {"src": n, "over": {}, "rows": {}, "cont": False, "last": True, "offset": 0,
                "dropped": n in dropped}
        if n in (GOAL_SLIDE, GOAL_SLIDE_WIDE):
            # One slide per goal, cloned from whichever stencil has enough
            # funding rows. A client with two goals gets two slides; one with
            # none gets neither. Goals needing more than GOAL_ROWS sources use
            # the wide stencil, the rest the narrow one.
            wide = n == GOAL_SLIDE_WIDE
            mine = [g for g in (goals or [])
                    if (len(g.get("sources", [])) > GOAL_ROWS) == wide]
            if not mine or n in dropped:
                pages.append(dict(page, dropped=True))
                continue
            prefix = "goal4" if wide else "goal"
            for k, goal in enumerate(mine):
                pages.append(dict(page, over=goal_tokens(prefix, goal), clone=k > 0))
            continue
        if n == OTHER_LOAN and loans is not None:
            extra = loans[1:]
            if not extra or n in dropped:
                pages.append(dict(page, dropped=True))
                continue
            for k, loan in enumerate(extra):
                pages.append(dict(page, over=row_tokens("loan", [loan], start=2), clone=k > 0))
            continue
        # A list whose slide carries no numbered tokens has nowhere to be
        # drawn -- that happens while a redesigned slide is waiting to be
        # re-tokenised. Skip it rather than failing the whole deck.
        paged = [p for p in by_slide.get(n, [])
                 if LISTS[p]["mode"] in ("page", "timeline")
                 and p in lists and (LISTS[p].get("cap") or caps.get(p))]
        if paged and not page["dropped"]:
            prefix = paged[0]
            # A list may declare a cap above the slots the design drew, where
            # the renderer builds its own rows rather than filling fixed ones.
            cap = LISTS[prefix].get("cap") or caps[prefix]
            items = lists[prefix]
            chunks = [items[i:i + cap] for i in range(0, len(items), cap)]
            for i, chunk in enumerate(chunks):
                pages.append(dict(page, rows={prefix: chunk}, cont=i > 0, last=i == len(chunks) - 1,
                                  offset=i * cap, clone=i > 0))
            continue
        page["rows"] = {p: lists[p] for p in by_slide.get(n, []) if p in lists}
        pages.append(page)
    return pages


# ------------------------------------------------------------- render

def render_page(page, root, values, samples, parts, allow_missing, missing, used):
    n = page["src"]
    local = dict(values, **page["over"])
    for prefix, items in page["rows"].items():
        spec = LISTS[prefix]
        local.update(row_tokens(prefix, items))
        groups = {}
        if spec["mode"] == "timeline":
            layout.timeline(root, items, prefix)
        else:
            groups = layout.keep_slots(root, prefix, len(items))
            layout.renumber(groups, page["offset"])
        if not page["last"] and spec.get("final"):
            rows = [sp for s, sps in groups.items() if s <= len(items) for sp in sps]
            layout.drop_final_only(root, spec["final"], keep=rows)
    if page["cont"]:
        layout.mark_continued(root)
    if n == ASSET_SLIDE and "_assets_rows" in values:
        # Allocation rows are numbered slots now, so keeping the first N rows
        # and closing the gaps is all the slide needs: the labels came from
        # the client's own asset classes rather than the nine drawn here.
        from pptx_derive import ALLOC_SLOTS
        order = [str(i) for i in range(1, ALLOC_SLOTS + 1)]
        kept = {str(i) for i in range(1, int(values["_assets_rows"]) + 1)}
        layout.keep_named(root, ASSET_TOKEN, kept, order, left=3.5)

    local.update(page_no=page["page_no"], page_total=page["page_total"])
    for k in DERIVED:
        local.setdefault(k, "")
    for t in root.iter(f"{{{A}}}t"):
        if t.text and "{{" in t.text:
            def sub(m):
                k = m.group(1)
                if k in local:
                    used.add(k)
                    return local[k]
                missing.setdefault(k, set()).add(page["page_no"])
                return f"[[{k}]]"
            t.text = TOKEN.sub(sub, t.text)
    for k in GRAPHIC_INPUTS.get(n, []):
        used.add(k)
        if k not in local:
            missing.setdefault(k, set()).add(page["page_no"])
    if not missing or allow_missing:
        try:
            graphics(n, root, parts, local)
        except KeyError as e:
            missing.setdefault(e.args[0], set()).add(page["page_no"])


def slide_order(z):
    pres = z.read("ppt/presentation.xml").decode("utf8")
    rels = z.read("ppt/_rels/presentation.xml.rels").decode("utf8")
    targets = {}
    for rel in re.findall(r"<Relationship [^>]*/>", rels):
        targets[re.search(r'Id="([^"]+)"', rel).group(1)] = re.search(r'Target="([^"]+)"', rel).group(1)
    return ["ppt/" + targets[r] for r in re.findall(r'<p:sldId [^>]*r:id="([^"]+)"', pres)]


def build(template, values, lists, include, allow_missing):
    samples = {k: v["sample"] for k, v in
               json.loads(MANIFEST.read_text(encoding="utf-8"))["tokens"].items()}
    with zipfile.ZipFile(template) as z:
        order = slide_order(z)
        caps = capacities(z, order)
        files = {i.filename: z.read(i.filename) for i in z.infolist()}
        infos = z.infolist()

    values, lists = format_numbers(values, lists, samples)
    values = derive(values, lists, samples)
    if lists.get("loan"):  # the home-loan section (slides 8, 21-25) is about the first loan
        values.update(row_tokens("loan", lists["loan"][:1]))
    pages = plan_slides(len(order), lists, caps, include, samples,
                        goals=lists.pop("goals", None))
    for prefix, spec in LISTS.items():  # charts elsewhere read these rows (cover, SIP ladder)
        if spec["mode"] in ("fold", "fixed") and prefix in lists:
            values.update(row_tokens(prefix, lists[prefix]))
    kept = [p for p in pages if not p["dropped"]]
    for i, p in enumerate(kept, 1):
        p["page_no"], p["page_total"] = f"{i:02d}", f"{len(kept):02d}"

    parts = {name: etree.fromstring(data) for name, data in files.items()
             if name.startswith(("ppt/charts/chart", "ppt/media/")) and name.endswith((".xml", ".svg"))}
    missing, used = {}, set()
    rendered = []
    for page in pages:
        root = etree.fromstring(files[order[page["src"] - 1]])
        if not page["dropped"]:
            render_page(page, root, values, samples, parts, allow_missing, missing, used)
        rendered.append(etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True))
    if missing:
        lines = [f"  {k}  (page {', '.join(sorted(p))})" for k, p in sorted(missing.items())]
        msg = f"{len(missing)} token(s) have no value:\n" + "\n".join(lines)
        if not allow_missing:
            sys.exit("error: " + msg + "\nAdd them to the values file, or pass --allow-missing for a draft.")
        print("warning: " + msg)
    for name, root in parts.items():
        decl = name.endswith(".xml")
        files[name] = etree.tostring(root, xml_declaration=decl, encoding="UTF-8",
                                     standalone=True if decl else None)
    package(files, order, pages, rendered)
    return files, infos, pages, values, lists, used


def package(files, order, pages, rendered):
    """Write each page into the package, cloning slides for extra pages."""
    pres = etree.fromstring(files["ppt/presentation.xml"])
    prels = etree.fromstring(files["ppt/_rels/presentation.xml.rels"])
    ctypes = etree.fromstring(files["[Content_Types].xml"])
    lst = pres.find("p:sldIdLst", NS)
    rid_of = {"ppt/" + r.get("Target"): r.get("Id") for r in prels}
    sld_of = {s.get(f"{{{R}}}id"): s for s in lst}
    next_id = max(int(s.get("id")) for s in lst) + 1
    next_num = max(int(re.search(r"(\d+)\.xml$", n).group(1)) for n in order) + 1
    next_rid = max(int(r.get("Id")[3:]) for r in prels if r.get("Id")[3:].isdigit()) + 1
    for s in list(lst):
        lst.remove(s)
    dropped = set()
    for page, xml in zip(pages, rendered):
        src = order[page["src"] - 1]
        if not page.get("clone"):
            files[src] = xml
            if page["dropped"]:
                dropped.add(src)  # left out of the deck; pruned below
                continue
            lst.append(sld_of[rid_of[src]])
            continue
        name = f"ppt/slides/slide{next_num}.xml"
        next_num += 1
        files[name] = xml
        rels = etree.fromstring(files[src.replace("slides/", "slides/_rels/") + ".rels"])
        for r in list(rels):
            if r.get("Type") == NOTES_TYPE:  # notes stay with the original slide
                rels.remove(r)
        files[name.replace("slides/", "slides/_rels/") + ".rels"] = etree.tostring(
            rels, xml_declaration=True, encoding="UTF-8", standalone=True)
        rid = f"rId{next_rid}"
        next_rid += 1
        etree.SubElement(prels, f"{{{PKG}}}Relationship", Id=rid, Type=SLIDE_TYPE,
                         Target=name[len("ppt/"):])
        etree.SubElement(ctypes, f"{{{CT}}}Override", PartName="/" + name,
                         ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml")
        sld = etree.SubElement(lst, f"{{{P}}}sldId", id=str(next_id))
        sld.set(f"{{{R}}}id", rid)
        next_id += 1
    for r in list(prels):
        if "ppt/" + r.get("Target") in dropped:
            prels.remove(r)
    for part, root in (("ppt/presentation.xml", pres), ("ppt/_rels/presentation.xml.rels", prels),
                       ("[Content_Types].xml", ctypes)):
        files[part] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    prune(files)


def _rels_of(part):
    head, tail = posixpath.split(part)
    return posixpath.join(head, "_rels", tail + ".rels")


def prune(files):
    """Drop every part no relationship reaches any more.

    Slides left out of the deck take their notes, charts and pictures with
    them, the same clean-up PowerPoint does when a slide is deleted -- done
    here so the deck needs no PowerPoint (the server runs Linux).
    """
    reached, todo = {"[Content_Types].xml"}, ["_rels/.rels"]
    while todo:
        rels_name = todo.pop()
        if rels_name in reached or rels_name not in files:
            continue
        reached.add(rels_name)
        base = posixpath.dirname(posixpath.dirname(rels_name))  # folder of the part the rels belong to
        for r in etree.fromstring(files[rels_name]):
            if r.get("TargetMode") == "External":
                continue
            target = r.get("Target")
            part = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(base, target))
            if part in files and part not in reached:
                reached.add(part)
                todo.append(_rels_of(part))
    for name in [n for n in files if n not in reached]:
        del files[name]
    ctypes = etree.fromstring(files["[Content_Types].xml"])
    for o in list(ctypes):
        if o.get("PartName") and o.get("PartName").lstrip("/") not in files:
            ctypes.remove(o)
    files["[Content_Types].xml"] = etree.tostring(ctypes, xml_declaration=True, encoding="UTF-8", standalone=True)


PS_EXPORT = r"""
param([string]$In, [string]$Pdf)
$app = New-Object -ComObject PowerPoint.Application
$p = $app.Presentations.Open($In, $true, $false, $false)
$p.SaveAs($Pdf, 32)
$p.Close(); $app.Quit()
"""


def export_pdf(pptx, pdf):
    """Export the PDF through PowerPoint (Windows only). The PPTX itself is
    complete without it."""
    with tempfile.TemporaryDirectory() as tmp:
        ps = Path(tmp) / "export.ps1"
        ps.write_text(PS_EXPORT, encoding="utf-8")
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps),
               "-In", str(pptx.resolve()), "-Pdf", str(pdf.resolve())]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"error: PowerPoint export failed (is {pptx.name} open?):\n{r.stderr or r.stdout}")


def main():
    ap = argparse.ArgumentParser(description="Populate the Goal Based Planning PPTX and export a PDF.")
    ap.add_argument("values", type=Path, help="client values JSON")
    ap.add_argument("-o", "--out", type=Path, help="output folder (default populated_<name>)")
    ap.add_argument("--template", type=Path, default=TEMPLATE)
    ap.add_argument("--allow-missing", action="store_true", help="render missing tokens as [[name]]")
    ap.add_argument("--no-pdf", action="store_true", help="write the PPTX only")
    args = ap.parse_args()

    values, lists, include = load(args.values)
    raw_keys = set(values) | set(lists)
    files, infos, pages, values, lists, used = build(args.template, values, lists, include, args.allow_missing)

    name = args.values.stem
    out = args.out or BASE / f"populated_{name}"
    out.mkdir(parents=True, exist_ok=True)
    pptx, pdf = out / f"{name}.pptx", None if args.no_pdf else out / f"{name}.pdf"
    written = {i.filename for i in infos}
    with zipfile.ZipFile(pptx, "w", zipfile.ZIP_DEFLATED) as w:
        for info in infos:
            if info.filename in files:  # parts of slides left out were pruned
                w.writestr(info, files[info.filename])
        for part in sorted(set(files) - written):
            w.writestr(part, files[part])
    record = {k: v for k, v in values.items() if not k.startswith("_") and not isinstance(v, (dict, list))}
    record.update({k: v for k, v in lists.items()})
    (out / "client_values.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    if pdf:
        export_pdf(pptx, pdf)

    kept = [p for p in pages if not p["dropped"]]
    conts = [p for p in pages if p.get("clone") and not p["dropped"]]
    omitted = sorted({p["src"] for p in pages if p["dropped"]})
    print(f"Populated {len(used)} tokens across {len(kept)} slides -> {out}")
    if conts:
        print(f"Added {len(conts)} continuation slide(s) for rows that did not fit on one page")
    if omitted:
        print(f"Omitted {len(omitted)} template slide(s) not applicable to this client: "
              + ", ".join(map(str, omitted)))
    unused = sorted(k for k in raw_keys - used - set(lists) - {"assets", "goals"}
                    if not any(k == t for p in pages for t in p["over"]))
    if unused:
        print(f"Note: {len(unused)} value(s) defined but unused: " + ", ".join(unused))
    print(pptx)
    if pdf:
        print(pdf)


if __name__ == "__main__":
    main()
