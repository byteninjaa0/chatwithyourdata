# Plan 0007 — FP-PPT-AI-NEW: bring slides 27–49 onto the Sep-27 deck

- **Status:** executed (2026-10-13, by Claude Code at the user's request; see "Execution notes")
- **Branch / PR:** `feat/fp-ppt-new-deck-slides-27-49`
- **Owner:** Claude Code (planner)

## Execution notes
- No branch was created: `FP-PPT-AI-NEW/` is untracked, so a branch would not isolate it. The
  `.pre_0007_backup/` snapshot is the rollback.
- Iyer also needed the redesigned marriage slide's values (`marriage_src*`, `marriage_intro`, …), which
  were missing before this plan. They were filled from the design samples, as for the rest of Iyer.
- `populate_pptx.py`'s "defined but unused" note no longer lists the `goals` list or the category-named
  `alloc_*_value/pct` keys. Both are consumed (by `plan_slides` and `pptx_derive`), and both were false
  positives.
- Results: `--verify` OK (49 slides, 637 tokens, no conflicts).
  - All four clients run without `--allow-missing`: Menon 45 slides, Iyer 48, maximal 56, minimal 34.
  - No `{{`/`[[` survives in any of them, and the Menon, maximal and minimal decks contain no sample
    strings.
  - Minimal still reports values left unused by the sections it deliberately drops (loans, legacy,
    executive summary). That is expected.
- Visual check done on Menon and maximal.
- Known cosmetic leftovers, out of scope:
  - Every goal slide shows the design's airplane icon.
  - Long advisor comments can touch the footer.
  - On one-child education slides, the panel-2 space stays empty.

## Goal
Make every slide of the 49-slide Goal Based Planning deck in `FP-PPT-AI-NEW/` render from the client's
values file: no sample-client text, no `[[token]]` placeholders, no sample graphics. Make all four example
clients run cleanly **without** `--allow-missing`.

## Context & rationale

All paths below are relative to `FP-PPT-AI-NEW/placeholder_template_package/` unless stated.

### What was found (audit on 2026-10-13)
The designed deck was replaced on Sep 27 (`Goal Based Plan Presentation Template 11Sep'26.pptx`, now
**49** slides). An extra slide was inserted, so everything from slide 28 onwards moved by one. Only part
of the code was updated:

| Area | State |
|---|---|
| `build_pptx_template.py` `SPEC` | Slides 1–27 and 29–34, 39, 40, 48, 49 are tokenised. **28 and 35–38 and 41–47 have no spec**, so they ship the sample client's text. |
| `populate_pptx.py` `SECTIONS` | Already on the new numbering. Correct. |
| `populate_pptx.py` `LISTS` | Still on the **old** numbering for every slide ≥ 39 (`action` 43, `suggestion` 44, `takeaway` 46, `corpus_breakup` 41, `corpus_now`/`corpus_later` 39). That is why Menon's `corpus_now_6/7` and `corpus_later_2` stay empty: the rows are attached to slide 39 (the ladder) instead of slide 40. |
| `pptx_graphics.py` `graphics()` | Still on old numbering: ladder chart `38`, corpus donut and annuity bars `41` with `image30/31.svg`, outcomes chart `45`, education charts `29/30` with `image19/21.svg`. |
| Client files | None define the new `ug_*` / `pg_*` tokens and none has a `goals` list, so all four runs fail (58 missing tokens). The goal slides 27 and 29 never appear. |

Measured result: every client fails without `--allow-missing`. With it, the Menon deck shows Iyer's
sample figures on PF (₹78 L), PPF, equity ("Aarav’s PG"), NPS, retirement outlook, corpus donut (₹5.50 Cr),
legacy, next steps, executive summary, outcomes and takeaways.

### Key finding: most of the missing specs are not lost, only mis-numbered
The old specs were tested against the current source deck. The specs in
`.pre_dynamic_assets_backup/build_pptx_template.beforeshift.py` for **old slides 40–46 match current source
slides 41–47 word for word (100% of strings each)**. The comments in the current file saying "Slide N
changed in the Sep-27 source deck; this spec no longer matches it" are wrong. They were commented out
because they sat under the wrong slide number. Re-enabling them under the new numbers is mechanical.

Only five slides were actually redesigned and need new specs:
- **28** Property Purchase — The Plot
- **35** Provident Fund
- **36** Public Provident Fund
- **37** Direct Equity
- **38** National Pension Scheme

### Decisions
1. **Slide 28 is not tokenised. It is always omitted.** It is the same layout as slide 27 (a goal with two
   funding rows), and `plan_slides()` already clones slide 27 once per goal in the client's `goals` list.
   Tokenising 28 would add a second, redundant goal stencil. The "plot" becomes a normal `goals` entry.
   The `vacation` / `property` / `construction` include switches are removed for the same reason. They
   drop whole stencils, which would hide *every* goal using that stencil. A goal is now removed with
   `"to_include": false` on the goal itself.
2. **Education becomes two per-child lists, `ug` and `pg`** (fixed mode, cap 2). Each item fills one child
   panel, and `layout.keep_slots()` removes panel 2 for one-child clients such as Menon. Unused funding
   source rows inside a panel are filled with `""` and render blank. Closing that gap is out of scope.
3. **The retirement asset slides get a new token, `asset_horizon_year`.** In the design, slides 35–38 say
   2037 while the rest of the deck says 2036 for `retirement_year`. One token cannot carry two samples
   (the build reports a conflict and `--verify` exits 1). `pptx_derive` defaults it to `retirement_year`,
   and a value stated in the file wins.
4. **Bar heights on slides 35–38 are redrawn from the values**, the same as every other graphic. Tokenising
   only the labels would leave the sample client's bar heights next to the client's numbers.

## Affected files
All under `FP-PPT-AI-NEW/`:
- `placeholder_template_package/build_pptx_template.py` — **edit** (`SPEC`, `GRAPHICS`, remove stale comment blocks)
- `placeholder_template_package/populate_pptx.py` — **edit** (`SECTIONS`, `SECTION_ALIASES`, `LISTS`, `GRAPHIC_INPUTS`, `load()`, `plan_slides()`, `render_page()`)
- `placeholder_template_package/pptx_derive.py` — **edit** (`derive()`: `asset_horizon_year`, `ug_years`, `pg_years`, blank source rows)
- `placeholder_template_package/pptx_graphics.py` — **edit** (`graphics()` renumbering; new bar redraws for 35–38; remove `education_buildup`)
- `placeholder_template_package/clients/menon_example.json`, `iyer_example.json`, `pptx_test_maximal.json`, `pptx_test_minimal.json` — **edit**
- `placeholder_template_package/financial_plan_template.pptx`, `pptx_template_tokens.json` — **regenerated** by the build, not hand-edited
- `placeholder_template_package/populated_menon_example/`, `populated_iyer_example/` — **regenerated**
- `README.md`, `placeholder_template_package/README.md` — **edit**
- `placeholder_template_package/.pre_0007_backup/` — **create** (snapshot, step 0)

## Implementation steps

### Step 0 — Snapshot and branch
`FP-PPT-AI-NEW/` is untracked in git and holds 25–33 MB binaries. Do not commit it as part of this plan.
1. `git checkout -b feat/fp-ppt-new-deck-slides-27-49`
2. Copy `build_pptx_template.py`, `populate_pptx.py`, `pptx_derive.py`, `pptx_graphics.py`,
   `pptx_layout.py`, `pptx_template_tokens.json`, `financial_plan_template.pptx` and `clients/` into
   `placeholder_template_package/.pre_0007_backup/`. This follows the existing
   `.pre_dynamic_assets_backup/` convention.
3. Run every Python command in this plan with `../.venv/Scripts/python.exe`, from
   `placeholder_template_package/`.

### Step 1 — `build_pptx_template.py`: re-enable the mis-numbered specs (mechanical)
Uncomment the existing commented blocks and **re-key** them as follows. The content is unchanged:

| Commented block currently labelled | Re-key to | Slide |
|---|---|---|
| `# 42: [` (retirement_monthly_expense, rental_income, annuity_required, retirement_summary_1/2) | `41` | Retirement Outlook |
| `# 41: list(zip(` (corpus_breakup rows + annuity_comment) | `42` | Corpus & Annuity |
| `# 45: [` (legacy_* notes + legacy_comment) | `43` | Legacy & Estate |
| `# 43: list(zip(` (action rows) | `44` | Next Steps |
| `# 44: list(zip(` (suggestion rows + suggestions_comment) | `45` | Executive Summary |
| `# 47: [` (outcomes_headline …) | `46` | Client Outcomes |
| `# 46: list(zip(` (takeaway rows + next_step) | `47` | Key Takeaways |

Delete the misleading "Slide N changed in the Sep-27 source deck … rewrite when wiring" comments above
them. Keep `SPEC` keys in ascending order.

### Step 2 — `build_pptx_template.py`: new specs for the redesigned slides 35–38
Add these entries. The strings are copied from the source deck. If the build reports
`'…' occurrence 1 not found`, the cause is whitespace or a soft line break in the source. Re-copy the exact
paragraph text with the dump command at the end of this step. That is not a design change.

```python
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
```
"lump sum, 60%" and "to annuity, 40%" stay static, because the 60/40 split is statutory. The titles
("Provident Fund" and so on) stay static.

Dump command (exact paragraph text of a source slide):
```bash
../.venv/Scripts/python.exe -c "import zipfile,sys;from lxml import etree;A='http://schemas.openxmlformats.org/drawingml/2006/main';z=zipfile.ZipFile(\"../Goal Based Plan Presentation Template 11Sep'26.pptx\");x=etree.fromstring(z.read(f'ppt/slides/slide{sys.argv[1]}.xml'));[print(repr(''.join(t.text or '' for t in p.iter('{%s}t'%A)).strip())) for p in x.iter('{%s}p'%A)]" 35
```
(`ppt/slides/slideN.xml` equals deck position N for slides 35–38. That was checked.)

### Step 3 — `build_pptx_template.py`: education headers, cleanup, `GRAPHICS`
1. In `SPEC[30]`, replace `("GOAL · 2032 AND 2037", "GOAL · {{ug_1_year}} AND {{ug_2_year}}")` with
   `("GOAL · 2032 AND 2037", "GOAL · {{ug_years}}")`. In `SPEC[31]`, replace the equivalent entry with
   `"GOAL · {{pg_years}}"`. This lets a one-child client read "GOAL · 2034".
2. Delete every remaining commented-out "Superseded" / "redesigned" SPEC block: old vacation 27, goal2 28,
   education 29, old marriage 32, old PF/NPS/PPF/equity 34–37, and the blocks moved live in step 1. The
   snapshot in `.pre_0007_backup/` keeps them.
3. Rewrite `GRAPHICS` to the new numbering:
   `3, 5, 6, 7, 13` unchanged; `18, 23, 24, 25` unchanged; remove `29` and `30` (the education SVGs are no
   longer in the deck); add `35: "PF balance bars: shape heights sized to the projected balance."`,
   `36: "PPF stacked bars: custGeom paths sized to contributions and interest."`,
   `37: "Equity split bar: earmarked vs retained widths."`,
   `38: "NPS bars: value at retirement vs at maturity."`; `38 → 39` ladder chart4;
   `41 → 42` with text `"Corpus donut (SVG image32.svg) and annuity bar chart (SVG image33.svg)."`;
   `45 → 46` outcomes chart5.
4. Run `python build_pptx_template.py --verify`. It must print `verify: OK` and report **no** sample
   conflicts. This regenerates `financial_plan_template.pptx` and `pptx_template_tokens.json`.

### Step 4 — `populate_pptx.py`
1. `SECTIONS`: remove `"vacation"`, `"property"` and `"construction"`. Leave the rest as is (already
   correct for the 49-slide deck).
2. Replace `SECTION_ALIASES` with:
   ```python
   # Include switches from the 48-slide deck. Goal slides are now one per entry
   # in "goals", so a goal is dropped with "to_include": false on the goal.
   DEPRECATED_INCLUDES = {"vacation", "goal2", "property", "construction"}
   ```
   In `load()`, pop these keys from `include`. If any were present, print one line to stderr:
   `warning: include.<key> is ignored; set "to_include": false on the goal instead`. Then run the
   existing unknown-section check.
3. Add `STENCIL_ONLY = {28}` beside `GOAL_SLIDE` with the comment "the design's plot goal: same shape as
   slide 27, which is cloned per goal, so the slide itself never ships". In `plan_slides()`, add
   `dropped |= STENCIL_ONLY` right after `dropped` is built.
4. `LISTS`: renumber `"action"` 43→44, `"suggestion"` 44→45, `"takeaway"` 46→47, `"corpus_breakup"`
   41→42, and `"corpus_now"` and `"corpus_later"` 39→40. Add:
   ```python
   "ug": {"slide": 30, "mode": "fixed", "drop_empty": True},
   "pg": {"slide": 31, "mode": "fixed", "drop_empty": True},
   ```
   In `plan_slides()`, extend the "empty table is dropped" loop so it also drops `spec["slide"]` when
   `spec.get("drop_empty")` and the list is present but empty.
5. `GRAPHIC_INPUTS`: `45` → `46`.
6. Update the "Slides that can be dropped" comment block to describe the 49-slide numbering in one or two
   lines. Remove the sentence about vacation/plot/construction sections.

### Step 5 — `pptx_derive.py` `derive()`
Add the following, each only when the key is absent (a stated value wins, as for every other derived value):
- `asset_horizon_year` = `retirement_year`.
- `ug_years` = the `year` of each kept `ug` item joined with `" AND "` (for example `"2032 AND 2037"`, or
  `"2034"` for one child). Same for `pg_years` from `pg`.
- For each kept `ug` item, `src1`–`src2` `label`/`value` fields default to `""`. For `pg`, `src1`–`src4`
  default to `""`. (Panel 1 of PG draws three source rows and panel 2 draws four. Fill all four for both;
  extras are ignored.) A client with fewer sources then renders blank rows instead of `[[…]]`.

`ug`/`pg` items are flat dicts: `child, year, target, basis, src1_label, src1_value, src2_label, …,
corpus, note` (`note` is UG only). They become `ug_1_child`, `ug_1_src1_label` and so on through the
existing `row_tokens()`. `ug_combined_required`, `ug_combined_corpus`, `ug_monthly`, `ug_comment` and the
`pg_` equivalents stay scalar values.

### Step 6 — `pptx_graphics.py` `graphics()`
1. Renumber: `elif n == 38:` → `39` (chart4 ladder). `elif n == 41:` → `42`, with `image30.svg` →
   `image32.svg` (donut) and `image31.svg` → `image33.svg` (annuity bars). These were checked: same element
   structure as before (8 circles + 2 texts; 6 rects + 16 texts). `elif n == 45:` → `46` (chart5).
2. Delete the `n == 29` (image19) and `n == 30` (image21 / `education_buildup`) branches and the
   `education_buildup()` function. Neither SVG exists in the new deck.
3. Add bar redraws. Shapes are found by name with the module's existing `shapes(root)` lookup. Distances
   are in inches, using the existing `geom`/`EMU` helpers. Add a small helper
   `set_y(sp, y_in, h_in=None)` mirroring `set_x`.
   - **Slide 35 (PF):** bars `Google Shape;1284;p42`, `…1287;p42`, `…1290;p42`, `…1293;p42`; value labels
     `…1283;p42`, `…1286;p42`, `…1289;p42`, `…1292;p42`. Values are `money(v["pf_bar_i_value"])`.
     Baseline 8.66 in, tallest bar 3.29 in. `h_i = max(0.30, 3.29 * val_i / max(vals))`,
     bar `y = 8.66 - h_i`, label `y = bar_y - 0.53`.
   - **Slide 38 (NPS):** bars `…1373;p44` (value `nps_value_at_retirement`) and `…1376;p44` (value
     `nps_maturity_value`); labels `…1372;p44` and `…1375;p44`. Baseline 8.66 in, tallest 3.21 in, same
     formula, label `y = bar_y - 0.60`.
   - **Slide 37 (equity):** `segmented_bar(sh, [("Google Shape;1409;p45", "Google Shape;1410;p45", earmarked, v["equity_earmarked_value"]), ("Google Shape;1411;p45", "Google Shape;1412;p45", retained, v["equity_retained_value"] + " retained for retirement")], x0=0.92, x1=10.73)`,
     with `earmarked = money(v["equity_earmarked_value"])` and `retained = money(v["equity_retained_value"])`.
     Afterwards, move the captions under each segment to that segment's x: `…1413;p45` and `…1414;p45`
     follow 1409, and `…1415;p45` follows 1411. When `earmarked == 0`, `segmented_bar` hides that segment;
     also remove 1413 and 1414.
   - **Slide 36 (PPF):** the stacked columns are two freeform shapes, `…1335;p43` (grey contributions, 4
     columns) and `…1336;p43` (navy interest, columns 2–4). Rebuild both `a:custGeom/a:pathLst/a:path`
     elements:
     - Inputs: `c_i = float(v["ppf_bar_i_contrib"])`, `t_i = float(v["ppf_bar_i_interest"] or 0)`
       (`t_1 = 0`), i = 1..4.
     - Frame: keep 1335's x (1.50 in) and cx. Set y = 8.42 − 2.90 and cy = 2.90 in. Give 1336 exactly the
       same off/ext. Set each path's `w`/`h` to the frame's cx/cy in EMU.
     - Columns: left edges at EMU offsets `0, 2375916, 4750308, 7124700`, width `1583436` (taken from the
       current path). `scale = cy / max(c_i + t_i)`.
     - Grey column i: rectangle from `cy - c_i*scale` to `cy`. Navy column i (skip when `t_i == 0`):
       rectangle from `cy - (c_i+t_i)*scale` to `cy - c_i*scale`. Each rectangle is
       `moveTo, lnTo ×3, close`, as in the source.
     - Labels (baseline 8.42 in, label height 0.35 in): contribution labels `…1338–1341;p43` at
       `y = 8.42 - c_i*scale_in/2 - 0.175`; interest labels `…1342–1344;p43` (columns 2–4) at
       `y = 8.42 - (c_i + t_i/2)*scale_in - 0.175`; totals `…1345–1348;p43` at
       `y = 8.42 - (c_i+t_i)*scale_in - 0.40`. Here `scale_in` is the scale in inches. Set a label's text
       to `""` when its segment is shorter than 0.35 in.

### Step 7 — Client files (all four)
Make every file produce **zero** missing tokens and **zero** "defined but unused" values.
1. **Remove stale keys:** `vacation_*`, `goal2_*`, `edu_*`, `education_comment`, the old scalar
   `ug_future_cost/ug_monthly_savings/ug_lumpsum/ug_asset_class/ug_roi/ug_corpus`, the same `pg_*` set,
   `pf_frequency`, `pf_alt_roi`, `pf_value_alt`, `ppf_frequency`, `ppf_extended_year`,
   `ppf_value_extended`, `nps_available_at_retirement`, `equity_top3_share` (rename it to
   `equity_top_weight`), `equity_tagged_goal`, `equity_tagged_year`. Also remove the `include.vacation`
   and `include.goal2` keys.
2. **Add a `goals` list.** Convert each client's old `vacation_*` and `goal2_*` values into two entries.
   Each entry has `name, year, cost_label ("Cost today"), cost_today, inflation_label ("Inflation
   assumed"), inflation, years_left, future_cost, intro, sources[{label, terms, value}], margin, corpus,
   redirect_label, redirect_to, comment`.
   - `sources[0]`: label `"SIP <sip> a month"`, terms `"<return> assumed · <years_left*12> months"`,
     value = the SIP's future value.
   - `sources[1]`: label `"Existing holding, re-tagged"`, terms `"<present_value> today · <return>"`,
     value = the future value of `present_value`.
   - `corpus` = the old `*_projected_corpus`. `margin` = `"<corpus − future_cost> clear of the target"`.
   - `comment` = the old `*_comment`. `intro` = one sentence on how the goal is funded.
   - `redirect_label` = `"From April <year> the <sip> SIP redirects to"`; `redirect_to` = the next goal's
     name and year, or `"Retirement corpus"`.

   A goal with more than 2 sources uses the wide stencil (slide 29). For `pptx_test_maximal`, add a third
   goal with 4 sources so the wide stencil is exercised.
3. **Add `ug` and `pg` lists plus their scalars.**
   - **Menon, maximal, minimal** (one child, Dev): build from the old `edu_ug_*` / `ug_*` and `edu_pg_*` /
     `pg_*` values.
     - UG: `child "DEV"`, `year 2034`, `target` = old `ug_future_cost`,
       `basis "₹20 L today, at 8% education inflation over 8 years"`,
       `src1_label "SIP ₹16,000 · Hybrid + flexicap · 11%"`,
       `src2_label "Lumpsum ₹6.0 L from mutual funds"`, `corpus` = old `ug_corpus`,
       `note "₹16,000 redirects to Dev’s PG from April 2034."`
     - PG: three sources (the PG SIP, the redirected UG SIP, the lumpsum).
     - `ug_combined_required`/`ug_combined_corpus` equal the single child's target/corpus.
       `ug_monthly` = the SIP. `ug_comment` / `pg_comment` = a split of the old `education_comment`.
   - **Minimal:** keep `ug` with one child and set `"pg": []`, so the PG slide is dropped (exercises
     `drop_empty`).
   - **Maximal:** two children for both `ug` and `pg` (copy Iyer's lists). Update its
     `children_names_ages` to `"1. Dev, 10       2. Mira, 6"`.
   - **Iyer** stays the "mirror of the design": take its `ug`/`pg` values from the samples in
     `pptx_template_tokens.json`, but name the second child **ISHA** (Iyer's real second child) instead of
     the design's "IRA".
4. **New retirement-asset keys** (all clients): `pf_description, pf_bar_1..4_value/year, pf_value_note,
   pf_recommendation; ppf_description, ppf_accounts, ppf_value_note, ppf_recommendation,
   ppf_bar_1..4_contrib/total/year, ppf_bar_2..4_interest; equity_top_weight, equity_current_value_caps,
   equity_earmarked_value/label/year, equity_retained_value/note, equity_base_year, equity_growth_value,
   equity_value_at_retirement_long, equity_recommendation; nps_description, nps_value_at_retirement,
   nps_gap_label, nps_lumpsum, nps_annuity, nps_recommendation`.
   - Bar years are `review_year`, +5, +8 and `asset_horizon_year`. Bar values are the existing balance
     compounded at the stated ROI.
   - Generic sentences (`*_description`, `*_recommendation`) may reuse the design's wording, with years
     and ages changed to the client's.
   - `nps_lumpsum` and `nps_annuity` = 60% and 40% of `nps_maturity_value`.
   - **Iyer** may take every value from the design samples.

### Step 8 — Regenerate outputs and READMEs
1. Regenerate `populated_menon_example/` and `populated_iyer_example/` with PDFs:
   `python populate_pptx.py clients/menon_example.json` and the same for Iyer.
2. Root `README.md`:
   - "48-slide" → "49-slide".
   - Document the `goals` list (fields, two-source vs four-source stencil, `to_include`).
   - Document the `ug`/`pg` lists (one panel per child, cap 2, `[]` drops the slide).
   - Document `asset_horizon_year`.
   - State that `include.vacation`/`goal2` are deprecated.
   - Update the maximal/minimal slide counts to what the runs print.
   - Remove "Speaker notes … still quote the sample client" only if it is no longer true. (It still is,
     so keep it.)
3. `placeholder_template_package/README.md`: "48-slide" → "49-slide".

## Contract / interface changes
Changes to the client values-file format (this package only; nothing in the main app reads it):
- New lists: `goals` (now required in practice to render goal slides), `ug`, `pg`.
- New scalars: listed in step 7.4, plus `asset_horizon_year`, `ug_years` and `pg_years` (derived).
- Removed keys: listed in step 7.1.
- `include` no longer accepts `vacation`, `goal2`, `property` or `construction` (warned and ignored).

## Env / ports touched
None. The script is offline. PDF export needs Windows with PowerPoint installed (unchanged).

## Acceptance criteria & how to verify
Run from `FP-PPT-AI-NEW/placeholder_template_package/`:
1. `../.venv/Scripts/python.exe build_pptx_template.py --verify` → `49 slides`, `verify: OK`, no conflict
   lines, exit 0.
2. For each of the four clients, `../.venv/Scripts/python.exe populate_pptx.py clients/<c>.json -o <tmp>/<c> --no-pdf`
   (no `--allow-missing`):
   - exits 0;
   - prints **no** "values defined but unused" note;
   - prints no `ppt/media/*.svg` missing line.
3. No placeholder survives. This prints nothing for all four outputs:
   `python -c "import zipfile,sys,re;z=zipfile.ZipFile(sys.argv[1]);[print(n) for n in z.namelist() if n.startswith('ppt/slides/slide') and re.search(rb'\{\{|\[\[',z.read(n))]" <out>.pptx`
4. **Sample-leak check on Menon.** Its text must contain none of: `Aarav`, `Ira`, `Isha`, `₹78 L`,
   `₹5.50 Cr`, `The Plot`, `Exit from FD or reallocate`, `Rohan`. Use the same zip-text scan as in check 3,
   searching for these strings.
5. Slide 28 is listed in every run's "Omitted … slides". Menon's deck has one UG panel and one PG panel.
   Minimal has no PG slide. Maximal includes a four-source goal slide.
6. **Visual check (required: bar geometry can't be verified by text).** Export the Menon and maximal decks
   to PNG through PowerPoint and review slides 30, 31, 35–38, 40, 42, 46 and 47. Check that bars are
   proportional to their labels, labels sit on or above their bars, no text overflows, and panel 2 is
   cleanly removed for one-child clients. PowerShell:
   `$a=New-Object -ComObject PowerPoint.Application;$p=$a.Presentations.Open("<abs>.pptx",$true,$false,$false);$i=0;foreach($s in $p.Slides){$i++;$s.Export("<dir>\s$i.png","PNG",1280,720)};$p.Close();$a.Quit()`
7. Slides 1–26 of the Menon deck are unchanged from the pre-change draft. Diff the slide XML of slides
   1–26 against a run of the `.pre_0007_backup` code.

## Tests
There is no automated test suite for this package. Checks 1–5 above are scripted one-liners; run them
for all four clients. Check 6 is manual, because bar and panel geometry needs eyes on the render.

## Risks & rollback
- **`keep_slots` on side-by-side panels.** `slot_groups()` assigns static shapes by row bands, but the
  UG/PG panels sit side by side. Panel-2 card backgrounds might not be removed, or panel-1 decoration
  might be. Check 6 catches this. If it happens, stop and report back to the planner for a revised plan.
  Don't improvise a new grouping rule.
- **Exact-string matching in step 2.** Source paragraphs with soft breaks may need re-copying with the
  dump command. That is allowed. Changing what a spec *tokenises* is not.
- **Long client text overflowing.** This is a known limit (README). Note any offender in the PR; don't
  resize boxes in this plan.
- **Rollback:** copy everything back from `.pre_0007_backup/`.

## Out of scope
- Anything outside `FP-PPT-AI-NEW/`, in particular `Financial_Planning/Utilities/ppt_*.py` (the
  production PPT path is separate).
- Collapsing blank source rows inside UG/PG panels and goal cards.
- Speaker notes.
- Wiring this package to the app or to Airtable data.
- Changing the design deck itself.
- Committing the binaries or the `.venv/` to git.

## Docs to update
- `FP-PPT-AI-NEW/README.md` and `FP-PPT-AI-NEW/placeholder_template_package/README.md` (step 8).
- `PROJECT_OVERVIEW.md`: **none**. It doesn't reference `FP-PPT-AI-NEW/` (checked with grep), and this
  change doesn't touch the app's routes, env vars, state or workflow nodes.
