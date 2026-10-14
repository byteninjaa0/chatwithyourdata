# Plan 0006 — Add Fixed Deposits and Insurance Cover slides

- **Status:** superseded (2026-10-14) — written for the old python-pptx deck, which was removed. The new deck covers FDs (slide 20) and insurance cover (slides 15, 16, 18); uncommitted work toward this plan is in git stash "legacy-ppt-pipeline: uncommitted edits…".
- **Branch / PR:** `feat/fd-and-insurance-cover-slides`
- **Owner:** Claude Code (planner)

## Goal
Add two new conditional slides to the financial plan deck — **Fixed Deposits** and **Insurance Cover
(life + medical)** — positioned immediately after the Financial Health Checkup slide, each rendered only
when the client has the relevant data.

## Context & rationale

### What is missing today
Both datasets are captured at intake and reach `final_state`, but neither is rendered anywhere in the deck:

- **`investment_details.fixed_deposits`** (`backend-airtable/main.py:284-297`, plus a spouse FD appended
  at `main.py:458-462`) — fields: `name_of_bank`, `principal_amount`, `interest_rate`, `maturity_date`.
  FDs currently contribute to `liquid_pool` totals but are never itemised for the client.
- **`client_data.life_insurance`** (`main.py:534-538`) — `company_name`, `coverage_value`.
- **`client_data.medical_insurance`** (`main.py:541-550`) — `policy_type` ("Employer"/"Self"),
  `company_name`, `coverage_value`.

**Access path — verify this, it is easy to get wrong.** `life_insurance` and `medical_insurance` are
returned as top-level keys of the dict built by `airtable_record_to_client_data()`, but that whole dict
becomes `final_state['client_data']`. So inside the builder they are reached as
`self.final_state['client_data']['life_insurance']` — **not** `self.final_state['life_insurance']`.
Confirmed by `ClientsDashboard.tsx:1085-1086` (`detail?.client_data?.life_insurance`) and by
`basic_calculations_nodes.py:726` calling `sum_life_insurance_cover(state.get('client_data', {}))`.
Note this differs from `fixed_deposits`, which sits under
`client_data.investment_details.fixed_deposits`.

### Relationship to the existing LIC table
`build_ulips_slide` (`ppt_builder.py:879-977`) already renders an "INSURANCE POLICIES" table from
`investment_details.lic_policies`. That is a different dataset — LIC endowment policies — from the
life/medical **cover** this plan adds. Leave that slide untouched.

### Why placement drives the cost
Slides are addressed by hardcoded integer indices into the v2 stencil. Inserting two slides after
Financial Health (slide 6) shifts **every** subsequent stencil by +2. The runner's own comment
(`ppt_runner.py:177-180`) records that for conditional slides the literal appears in **two** places —
the build call and the `delete_list.append(...)` — and missing one of the pair causes deletion to remove
the wrong slide, leaking empty stencils into client output. The renumbering table below is therefore the
critical part of this plan.

## Affected files
- `Financial_Planning/PPT_io/PPT_template/Financial Plan Stencil v2.pptx` — **edit (manual, in PowerPoint)**
- `Financial_Planning/Utilities/ppt_builder.py` — **edit** (two new methods)
- `Financial_Planning/Utilities/ppt_runner.py` — **edit** (two new calls + full renumbering)
- `Financial_Planning/tests/test_fd_insurance_slides.py` — **create**
- `PROJECT_OVERVIEW.md` — **edit** (slide inventory)

## Implementation steps

### Step 0 — Stencil first (manual, blocking)
This cannot be scripted and must happen before the code lands. The template is **not tracked in git**
(`PROJECT_OVERVIEW.md:265`) and lives on the server host, so the user does this in PowerPoint.

In `Financial Plan Stencil v2.pptx`, insert **two new slides at positions 7 and 8** (0-indexed),
i.e. immediately after the existing Financial Health Checkup slide at index 6:

- **New slide 7 — "Fixed Deposits"**: title textbox + one placeholder table. Match the visual style of
  the existing Liabilities slide (index 7 pre-change), since the FD builder mirrors its logic.
- **New slide 8 — "Insurance Cover"**: title textbox only, **no placeholder table**. Two tables are
  added programmatically with section headings, exactly like `build_ulips_slide`.

Everything from the old index 7 onward shifts down by 2. Do not reorder anything else.

### Step 1 — `build_fixed_deposits_slide` in `ppt_builder.py`
Add next to `build_liabilities_slide` (around line 829), following its structure exactly — including
removing the stencil's placeholder table before adding the dynamic one:

```python
    def build_fixed_deposits_slide(self, slide=7):
        """Build Fixed Deposits slide - dynamically populates FD table.

        Conditional: only runs if fixed deposits exist.
        Returns True if populated, False if slide should be deleted.
        """
        investment_details = self.final_state.get('client_data', {}).get('investment_details', {})
        fixed_deposits = investment_details.get('fixed_deposits', []) or []

        if not fixed_deposits:
            return False

        print(f"Fixed Deposits: slide: {slide}")

        data = [["Bank / Institution", "Invested Amount", "Interest Rate", "Maturity Date"]]

        for fd in fixed_deposits:
            if not isinstance(fd, dict):
                continue
            rate = fd.get('interest_rate', 0) or 0
            data.append([
                fd.get('name_of_bank', ''),
                convert_currency(fd.get('principal_amount', 0)),
                f"{round(rate * 100, 2)}%",
                fd.get('maturity_date', '') or '-',
            ])

        if len(data) == 1:
            return False

        # Remove existing template table before adding dynamic one
        slide_obj = self.prs.slides[slide]
        for shape in slide_obj.shapes:
            if shape.has_table:
                sp = shape._element
                sp.getparent().remove(sp)
                break

        add_table_to_slide(
            slide=slide_obj, data=data,
            left=Inches(1.5), top=Inches(3),
            width=Inches(16.5), height=Inches(1.0 * len(data)),
            font_size=Pt(24), header_fill=RGBColor(47, 85, 151),
            header_font_color=RGBColor(255, 255, 255), font_color=RGBColor(0, 0, 0))

        return True
```

**Rate formatting:** `_rate()` in intake normalises >1 values to decimals (`main.py:643-646`), so
`interest_rate` is stored as e.g. `0.072`. `* 100` matches how `build_liabilities_slide:849` renders
rates. The `len(data) == 1` guard handles a list containing only non-dict junk.

### Step 2 — `build_insurance_cover_slide` in `ppt_builder.py`
Add immediately after the FD method. This follows `build_ulips_slide`'s two-section pattern (heading +
table, vertical cursor) rather than the Liabilities pattern, because it renders **two** tables:

```python
    def build_insurance_cover_slide(self, slide=8):
        """Build Insurance Cover slide - life cover table followed by medical cover table.

        Conditional: only runs if life or medical insurance exists.
        Returns True if populated, False if slide should be deleted.
        """
        client_data = self.final_state.get('client_data', {})
        life_data = client_data.get('life_insurance', []) or []
        medical_data = client_data.get('medical_insurance', []) or []

        if not life_data and not medical_data:
            return False

        print(f"Insurance Cover: slide: {slide}")

        slide_obj = self.prs.slides[slide]

        TABLE_LEFT     = Inches(1.5)
        TABLE_WIDTH    = Inches(16.5)
        ROW_HEIGHT_IN  = 1.0
        HEADING_H_IN   = 0.55
        HEADING_GAP_IN = 0.1
        SECTION_GAP_IN = 0.6
        START_TOP_IN   = 3.0

        next_top = START_TOP_IN

        def _add_section_heading(text):
            nonlocal next_top
            txBox = slide_obj.shapes.add_textbox(
                TABLE_LEFT, Inches(next_top), TABLE_WIDTH, Inches(HEADING_H_IN))
            tf = txBox.text_frame
            tf.word_wrap = False
            para = tf.paragraphs[0]
            run = para.add_run()
            run.text = text
            run.font.bold = True
            run.font.size = Pt(32)
            run.font.color.rgb = RGBColor(0, 0, 0)
            next_top += HEADING_H_IN + HEADING_GAP_IN

        if life_data:
            _add_section_heading("LIFE INSURANCE")
            life_rows = [["Insurer", "Cover Value"]]
            for policy in life_data:
                life_rows.append([
                    policy.get('company_name', '') or '-',
                    convert_currency(policy.get('coverage_value', 0)),
                ])
            add_table_to_slide(
                slide=slide_obj, data=life_rows,
                left=TABLE_LEFT, top=Inches(next_top),
                width=TABLE_WIDTH, height=Inches(ROW_HEIGHT_IN * len(life_rows)),
                font_size=Pt(24), header_fill=RGBColor(70, 130, 180),
                header_font_color=RGBColor(255, 255, 255), font_color=RGBColor(0, 0, 0))
            next_top += ROW_HEIGHT_IN * len(life_rows) + SECTION_GAP_IN

        if medical_data:
            _add_section_heading("MEDICAL INSURANCE")
            med_rows = [["Policy Type", "Insurer", "Cover Value"]]
            for policy in medical_data:
                med_rows.append([
                    policy.get('policy_type', '') or '-',
                    policy.get('company_name', '') or '-',
                    convert_currency(policy.get('coverage_value', 0)),
                ])
            add_table_to_slide(
                slide=slide_obj, data=med_rows,
                left=TABLE_LEFT, top=Inches(next_top),
                width=TABLE_WIDTH, height=Inches(ROW_HEIGHT_IN * len(med_rows)),
                font_size=Pt(24), header_fill=RGBColor(128, 128, 128),
                header_font_color=RGBColor(255, 255, 255), font_color=RGBColor(0, 0, 0))

        return True
```

Note the stencil slide has **no** placeholder table (step 0), so there is no table-removal block here —
matching `build_ulips_slide`, which also adds its tables from scratch.

### Step 3 — Wire both into `populate_presentation` (`ppt_runner.py`)
Insert immediately after the financial health call at line 144-145, **before** the liabilities block:

```python
    has_fds = builder.build_fixed_deposits_slide(slide=7)
    if not has_fds:
        delete_list.append(7)

    has_insurance_cover = builder.build_insurance_cover_slide(slide=8)
    if not has_insurance_cover:
        delete_list.append(8)
```

Do **not** touch `builder.slide_offset` — these are fixed stencil slides, not duplicated inserts. The
`slide_offset` mechanism exists only for education/marriage/misc which duplicate slides per child/goal.

### Step 4 — Renumber every downstream literal (+2)
This is the error-prone part. Apply **all** of these in `ppt_runner.py`. For conditional slides both the
build call and the `delete_list` entry must change together:

| Slide | Old | New | Lines (pre-change) |
|---|---|---|---|
| liabilities (+ delete) | 7 | **9** | 146, 148 |
| retirement outlook | 9 | **11** | 150-151 |
| retirement goal planning | 10 | **12** | 152-153 |
| epf (+ delete) | 11 | **13** | 155, 157 |
| ppf (+ delete) | 13 | **15** | 159, 161 |
| education summary (+ delete) | 14 | **16** | 171, 174 |
| education details (+ delete) | 15 | **17** | 171, 175 |
| ulips base (+ delete) | 16 | **18** | 181, 184 |
| ssy base (+ delete) | 17 | **19** | 186, 189 |
| marriage base (+ delete) | 18 | **20** | 191, 194 |
| misc base (+ delete) | 19 | **21** | 196, 199 |
| wealth created base | 20 | **22** | 201-203 |
| rsu/esop base (+ delete) | 21 | **23** | 205, 208 |
| `TERM_COVER_TEMPLATE_SLIDE` | 22 | **24** | 83 |

Also update the two stale literals in the print statements at lines 202 and 222 so the debug output does
not lie about which template index it used.

The `+ builder.slide_offset` arithmetic on the >=18 (new numbering) entries stays exactly as-is — only
the base literal changes. Leave the ordering comment at lines 163-180 intact; it is still accurate, just
with shifted numbers.

`_resolve_term_cover_slide` (`ppt_runner.py:86-98`) searches for placeholder text first and only falls
back to the literal, so it self-heals — but update the constant anyway so the fallback stays correct.

## Contract / interface changes
None. No API route, env var, or state-shape change. Two new `PPTBuilder` methods; no workflow node or
edge changes.

## Env / ports touched
None.

## Acceptance criteria & how to verify

1. **Both slides render.** Run a plan for a client with FDs, life insurance, and medical insurance.
   The deck shows a Fixed Deposits table (bank / amount / rate / maturity) at slide 7 and an Insurance
   Cover slide at 8 with LIFE INSURANCE and MEDICAL INSURANCE sections.
2. **Rates format correctly.** FD interest shows e.g. `7.2%`, not `0.072%` or `720%`.
3. **Both slides drop cleanly when empty.** Run a client with no FDs and no insurance — both slides are
   deleted and **no blank stencil leaks into the deck**. This is the specific failure mode the runner
   comment warns about.
4. **Partial insurance data.** Client with life cover but no medical → slide renders with only the LIFE
   INSURANCE section, no stray heading or empty table. And vice versa.
5. **Nothing downstream shifted.** In the same run confirm every later slide still renders its own
   content — especially marriage, misc goals, and term cover, which are the offset-sensitive ones. Check
   the `[MARRIAGE-DEBUG]` output at lines 212-215 for a sane `delete_list`.
6. **Multi-child regression.** Run a client with 2+ children (so education inserts slides and
   `slide_offset` > 0) **and** missing FD/insurance. This is the case where an incorrect renumbering
   surfaces — verify ulips/ssy/marriage/misc/wealth/rsu all still land correctly.
7. **End to end.** `curl :8001/health` OK; Make plan → `POST /api/financial-plan/ppt` returns a valid
   .pptx.

## Tests
Create `Financial_Planning/tests/test_fd_insurance_slides.py`, matching the existing convention (plain
pytest, direct import, dict-literal fixtures — see `test_retirement_annuity.py`). Since these methods
need a real `Presentation`, follow whatever mocking approach `backend/tests/test_ppt_runner.py` already
uses. Cover the pure data/branch logic:

- FD list present → returns `True`; absent / empty → returns `False`.
- `fixed_deposits` key missing entirely → `False`, no exception.
- Life only → `True`; medical only → `True`; neither → `False`.
- Rate `0.072` renders as `7.2%`.
- `coverage_value` of 0 or missing renders via `convert_currency` without raising.
- Non-dict junk in either list is skipped without raising.

## Risks & rollback

- **Renumbering is the main risk.** A missed literal silently shifts a later slide or deletes the wrong
  one — and it may only appear for clients with multiple children (where `slide_offset` > 0). Acceptance
  criteria 5 and 6 exist specifically to catch this; do not skip them.
- **Stencil/code coupling.** If the code ships before the stencil is updated on the server host, slides 7
  and 8 will be whatever was previously there and the deck will be wrong throughout. Ship the stencil
  first, and note it is not in git so it will not deploy automatically.
- **Rollback:** revert the branch and restore the previous stencil. Code changes are confined to two
  files plus one new test file.

## Out of scope
- `build_ulips_slide` — leave it entirely untouched.
- Merging LIC policies into the new Insurance Cover slide — they stay on the ulips slide.
- Any change to `slide_offset` mechanics or the education/marriage/misc duplication logic.
- Term insurance requirement slide (`build_term_cover_slide`) — unrelated to cover *held*.
- Reordering or restyling any existing slide.

## Docs to update
`PROJECT_OVERVIEW.md` — update the slide inventory to list the two new slides and the shifted indices of
everything after them. Per `CLAUDE.md` this is part of executing the plan, not optional cleanup.
