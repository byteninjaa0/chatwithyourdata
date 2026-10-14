# Goal Based Planning deck

The 49-slide Armstrong Capital "Goal Based Planning" client deck, built from
a planning-workflow run. The workflow's output is the only input; there are
no hand-written client files.

```
Airtable record
  → POST /financial-plan/run            planning workflow → workflow_state
  → Financial_Planning/PPTX_Migration    adapter.py: workflow_state → deck values
  → FP-PPT-AI-NEW (this folder)          populate_pptx.py: values → PPTX / PDF
```

## Getting a deck

From the API (port 8001), with the `workflow_state` a Make plan run returned:

```
POST /financial-plan/ppt-v2
{ "workflow_state": { ... }, "format": "pdf",
  "advisor": { "name": "...", "designation": "...", "email": "..." } }
```

`format` is `pptx` (default) or `pdf`; `advisor` is optional and fills the
contact slide.

From Python:

```python
from Financial_Planning.PPTX_Migration.deck import build_deck
deck = build_deck(workflow_state, pdf=True)   # deck.pptx, deck.pdf (bytes)
```

From the command line, for one or more saved states (a `workflow_state`, or a
whole `/financial-plan/run` response):

```bash
python -m Financial_Planning.PPTX_Migration.deck state.json [more.json ...] -o out_dir [--no-pdf]
```

Run everything from the repo root in the main `.venv`. The PDF is exported by
Microsoft PowerPoint, so it needs Windows with PowerPoint installed;
`--no-pdf` / `pdf=False` needs neither.

## Which slides a client gets

A section appears only when the workflow has data for it, as in the existing
builder (`ppt_runner.py`, preserved at git tag `legacy-ppt-pipeline`):

| Data in the workflow | Slides |
|---|---|
| Loans | home loan (8); every further loan its own slide (9) |
| Children with UG / PG goals | UG (30) and PG (31), one panel per child; a stage nobody has is dropped |
| A marriage goal | children's marriage (32) |
| SSY under a child | Sukanya Samriddhi (33) |
| EPF / PPF / NPS projected | PF (35), PPF (36), NPS (38) |
| LIC, ULIP, life or health cover | policies (16) |
| Fixed deposits | FDs (20) |
| Any other goal (vacation, home, car) | one goal slide each (27, or 29 for 3–4 funding sources) |

Not produced yet, because the workflow carries no data for them: cover
classification and suggestions (17, 19), the deposit-funded prepayment story
and loan-life charts (21–25), direct-equity holding detail (37), legacy (43),
the action plan (44) and the executive summary (45–47).

A run fails rather than ship a slide with a missing figure: every token on a
kept slide must have a value.

## What is where

```
FP-PPT-AI-NEW/
├── Goal Based Plan Presentation Template 11Sep'26.pptx   the designed deck
└── placeholder_template_package/
    ├── financial_plan_template.pptx   the design with {{tokens}}
    ├── pptx_template_tokens.json      every token, its slides and sample value
    ├── populate_pptx.py               values → slides kept, rows, PPTX, PDF
    ├── pptx_derive.py                 totals, shares, formatting
    ├── pptx_layout.py                 rows, continuation pages, road-map
    ├── pptx_graphics.py               charts, donuts, gauge, bars
    ├── build_pptx_template.py         design deck → token template
    └── client_runs/                   local test decks from real runs (git-ignored)

Financial_Planning/PPTX_Migration/
├── adapter.py    workflow_state → values, and which sections apply
├── schema.py     validates the values (rows typed; every key a real token)
├── deck.py       build_deck(): adapter + renderer in one call; CLI
└── endpoint.py   POST /financial-plan/ppt-v2
```

## When the design changes

Edit the designed deck, update `SPEC` in `build_pptx_template.py`, and run

```bash
python build_pptx_template.py --verify
```

from `placeholder_template_package/`. `--verify` fills every token with its
sample value and checks the result reproduces the designed deck's text
exactly. If slides move, update the slide numbers in `populate_pptx.py`
(`SECTIONS`, `LISTS`) and `pptx_graphics.py` (`graphics()`).

## Testing

`client_runs/` holds saved `final_state.json` files from real workflow runs.
Rebuild them all after a change:

```bash
python -m Financial_Planning.PPTX_Migration.deck FP-PPT-AI-NEW/placeholder_template_package/client_runs/*/final_state.json -o FP-PPT-AI-NEW/placeholder_template_package/client_runs
```

They contain real client data: keep them out of git.

## Known limits

- Speaker notes are not populated.
- Text much longer than the design's sample can overflow its box; check the PDF.
- The health score is computed in `adapter.py` (`_health_score`) from savings
  rate, EMI load, emergency reserve and liquidity, since the workflow has none.
