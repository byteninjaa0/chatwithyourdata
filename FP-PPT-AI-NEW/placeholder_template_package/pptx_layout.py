"""Row-level layout for the Goal Based Planning PPTX deck.

Each repeating table on a slide is a set of numbered slots (fd_1_*, fd_2_*, ...).
A slot's shapes are found from where they sit: its token text boxes, plus the
divider line under the row, the legend square and label beside it, or the card
it sits in. Unused slots are removed outright, so a client with two FDs gets a
two-row table rather than two filled rows and three blank ones.
"""
import copy
import re

from pptx_graphics import A, EMU, NS, P, geom

TOKEN = re.compile(r"\{\{([a-z0-9_]+)\}\}")
FOOTER_TOP = 10.2  # inches; footer text and page number sit below this


class Box:
    def __init__(self, sp):
        off, ext = geom(sp)
        self.x0 = int(off.get("x")) / EMU
        self.y0 = int(off.get("y")) / EMU
        self.x1 = self.x0 + int(ext.get("cx")) / EMU
        self.y1 = self.y0 + int(ext.get("cy")) / EMU

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2

    def contains(self, x, y):
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


def top_shapes(root):
    """Positioned top-level shapes (text boxes, rectangles, lines) of a slide."""
    tree = root.find("p:cSld/p:spTree", NS)
    return [sp for sp in tree if sp.tag in (f"{{{P}}}sp", f"{{{P}}}cxnSp")
            and sp.find(".//a:xfrm/a:off", NS) is not None]


def tokens_of(sp):
    return TOKEN.findall("".join(t.text or "" for t in sp.iter(f"{{{A}}}t")))


def text_of(sp):
    return "".join(t.text or "" for t in sp.iter(f"{{{A}}}t")).strip()


def slot_groups(root, slot_of, left=1.3):
    """{slot: [shapes]} for the slots named by slot_of(token) -> slot or None.

    A static shape joins a slot when it is the card holding that slot, sits
    inside such a card, or lies in the slot's row band (from the row's top to
    the next row's top) within the row's width, reaching `left` inches left
    for legend squares and labels.
    """
    shapes = top_shapes(root)
    groups, boxes, static = {}, {}, []
    for sp in shapes:
        slots = {slot_of(t) for t in tokens_of(sp)} - {None}
        if len(slots) == 1:
            groups.setdefault(slots.pop(), []).append(sp)
        elif not tokens_of(sp):
            static.append(sp)
    for s, sps in groups.items():
        bs = [Box(sp) for sp in sps]
        b = Box(sps[0])
        b.x0, b.y0 = min(x.x0 for x in bs), min(x.y0 for x in bs)
        b.x1, b.y1 = max(x.x1 for x in bs), max(x.y1 for x in bs)
        boxes[s] = b
    cards = {}
    for sp in static:
        bx = Box(sp)
        if bx.y0 >= FOOTER_TOP:
            continue
        held = [s for s, b in boxes.items() if bx.contains(b.cx, b.cy)]
        if len(held) == 1 and (bx.x1 - bx.x0) < 12:
            cards[id(sp)] = held[0]
            groups[held[0]].append(sp)
    for sp in static:
        if id(sp) in cards:
            continue
        bx = Box(sp)
        if bx.y0 >= FOOTER_TOP:
            continue
        owner = None
        for card in static:
            s = cards.get(id(card))
            if s is not None and card is not sp and Box(card).contains(bx.cx, bx.cy):
                owner = s
        if owner is None:
            for s, b in boxes.items():
                below = [o.y0 for t, o in boxes.items() if t != s and o.y0 > b.y0 + 0.1
                         and o.x0 < b.x1 and o.x1 > b.x0]
                bottom = min(below) if below else b.y1 + 0.35
                if (b.y0 - 0.05 <= bx.cy < bottom and bx.x0 >= b.x0 - left
                        and bx.x1 <= b.x1 + 0.3):
                    owner = s
                    break
        if owner is not None:
            groups[owner].append(sp)
    return groups


def remove(shapes):
    for sp in shapes:
        if sp.getparent() is not None:
            sp.getparent().remove(sp)


def move(shapes, dx, dy):
    for sp in shapes:
        off, _ = geom(sp)
        off.set("x", str(int(off.get("x")) + int(dx * EMU)))
        off.set("y", str(int(off.get("y")) + int(dy * EMU)))


def origin(shapes):
    bs = [Box(sp) for sp in shapes]
    return min(b.x0 for b in bs), min(b.y0 for b in bs)


def keep_slots(root, prefix, count, left=1.3):
    """Keep slots 1..count of prefix_N_* rows; remove the rest with their shapes."""
    rx = re.compile(rf"{re.escape(prefix)}_(\d+)_")
    groups = slot_groups(root, lambda t: int(m.group(1)) if (m := rx.match(t)) else None, left)
    for s, sps in groups.items():
        if s > count:
            remove(sps)
    return groups


def keep_named(root, rx, kept, order, left):
    """Keep the named slots in `kept`, closing gaps in `order` (reading order)."""
    groups = slot_groups(root, lambda t: m.group(1) if (m := rx.match(t)) else None, left)
    positions = [origin(groups[name]) for name in order if name in groups]
    for name, sps in groups.items():
        if name not in kept:
            remove(sps)
    for pos, name in zip(positions, [n for n in order if n in kept and n in groups]):
        x, y = origin(groups[name])
        move(groups[name], pos[0] - x, pos[1] - y)


def timeline(root, items, prefix="roadmap"):
    """Lay out len(items) road-map milestones evenly along the line.

    The design has four milestone styles: cards above the line (slot 1, and the
    taller slot 5), a card below it (slot 2) and a highlighted card below it
    (slot 4). Each item
    gets a copy of the right style, alternating above and below, and the
    highlighted style goes to the item marked "highlight": true, or else to
    the retirement goal.
    """
    rx = re.compile(rf"{prefix}_(\d+)_")
    shapes = top_shapes(root)
    spans = {}
    for sp in shapes:
        ss = {int(m.group(1)) for t in tokens_of(sp) if (m := rx.match(t))}
        if ss:
            s, b = ss.pop(), Box(sp)
            lo, hi = spans.get(s, (b.x0, b.x1))
            spans[s] = (min(lo, b.x0), max(hi, b.x1))
    groups = {s: [] for s in spans}
    for sp in shapes:
        b = Box(sp)
        if b.y0 < 2.4 or b.y0 >= FOOTER_TOP or b.x1 - b.x0 > 10:
            continue
        for s, (lo, hi) in spans.items():
            if lo - 0.2 <= b.cx <= hi + 0.2:
                groups[s].append(sp)
                break
    centre = {s: (lo + hi) / 2 for s, (lo, hi) in spans.items()}
    first, last = min(centre.values()), max(centre.values())
    hi = next((j for j, it in enumerate(items) if it.get("highlight") in (True, "true", "yes")), None)
    if hi is None:
        hi = next((j for j, it in enumerate(items) if "retire" in str(it.get("label", "")).lower()), None)
    flip = hi is not None and hi % 2 == 0  # put the highlighted item on a below-the-line slot
    tree = root.find("p:cSld/p:spTree", NS)
    count = len(items)
    for j in range(count):
        below = (j % 2 == 1) != flip
        # Above the line the design has a short card (slot 1) and a tall one
        # (slot 5) for labels that run to three lines.
        tall = len(str(items[j].get("label", ""))) > 30
        style = 4 if j == hi else (2 if below else (5 if tall else 1))
        target = (first + last) / 2 if count == 1 else first + (last - first) * j / (count - 1)
        for sp in groups[style]:
            clone = copy.deepcopy(sp)
            for t in clone.iter(f"{{{A}}}t"):
                if t.text:
                    t.text = t.text.replace("{{%s_%d_" % (prefix, style), "{{%s_%d_" % (prefix, j + 1))
            move([clone], target - centre[style], 0)
            tree.append(clone)
    for sps in groups.values():
        remove(sps)


def drop_final_only(root, tokens, keep=()):
    """On a non-final continuation page, remove totals and commentary.

    Everything from the first of `tokens` down to the footer goes, so the
    advice and the column totals appear once, at the end of the section.
    Shapes in `keep` (the rows on this page) stay.
    """
    keep = {id(sp) for sp in keep}
    shapes = [sp for sp in top_shapes(root) if id(sp) not in keep]
    tops = [Box(sp).y0 for sp in shapes if set(tokens_of(sp)) & set(tokens)]
    if not tops:
        return
    cut = min(tops) - 0.05
    remove([sp for sp in shapes if cut <= Box(sp).y0 < FOOTER_TOP])


def mark_continued(root, title_name="Text 1"):
    for sp in top_shapes(root):
        if sp.find(".//p:cNvPr", NS).get("name") == title_name:
            ts = [t for t in sp.iter(f"{{{A}}}t") if t.text]
            if ts:
                ts[-1].text = ts[-1].text + " (cont.)"
            body = sp.find("p:txBody/a:bodyPr", NS)
            if body is not None:  # the title box is sized to the title alone
                body.set("wrap", "none")
            return


def renumber(groups, offset):
    """Continuation pages carry on the item numbering: 01..06 becomes 07..12."""
    if not offset:
        return
    for s, sps in groups.items():
        for sp in sps:
            if text_of(sp) == f"{s:02d}" and not tokens_of(sp):
                t = next(t for t in sp.iter(f"{{{A}}}t") if t.text and t.text.strip())
                t.text = f"{s + offset:02d}"
