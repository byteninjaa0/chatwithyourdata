# Plan 0003 — Show spouse EPF only under Spouse Details (drop from client EPF)

- **Status:** ready-for-execution
- **Branch / PR:** fix/spouse-epf-spouse-only
- **Owner:** Claude Code (planner)

## Goal
Stop counting the spouse's provident fund inside the **client's** EPF total. The spouse EPF should
appear **only under Spouse Details**, not also in the Overview retirement table / client EPF math.

## Context & rationale
In `backend/airtable_main.py`, the spouse's PF (`spouse_pf_val` / `spouse_pf_contrib`, read at
lines 357–358 from `spouse_investment_pf_current_value` / `spouse_investment_pf_contribution`) is
written to **two** places:

1. `spouse_block["provident_fund"]` (lines 381–387) → rendered under **Spouse Details** as
   "Provident Fund (PF)" by `components/SpouseDetailsPanel.tsx`. ✅ keep.
2. Appended to the **client's** `epf_list` (lines 415–420) → folded into `retirement_investments.epf`,
   so it shows in the Overview "Retirement Investments" table (`ClientsDashboard.tsx:756`), inflates
   `epfVal` / `totalInvestments` / the portfolio pie (lines 542, 559, 574), **and** feeds the client's
   retirement EPF calculation in the workflow. ❌ this is the double-count to remove.

**User decision (confirmed):** show the spouse EPF only under Spouse Details — remove it from the
client's EPF list/total, accepting that it also leaves the client's retirement EPF math.

This is a backend data-mapping fix only; the Spouse Details rendering already reads `spouse.provident_fund`
independently, so it is unaffected.

## Affected files
- `backend/airtable_main.py` — **edit** (delete the spouse-PF → `epf_list` append).
- `PROJECT_OVERVIEW.md` — **edit** (mapping note).

## Implementation steps
1. In `backend/airtable_main.py`, **delete** the block at lines 415–420:
   ```python
   if spouse_pf_val or spouse_pf_contrib:
       epf_list.append({
           "current_value":                          spouse_pf_val,
           "employee_employer_contribution_monthly": spouse_pf_contrib,
           "interest_rate":                          0.085,
       })
   ```
   Leave everything else intact — `spouse_block["provident_fund"]` (lines 381–387) stays, so Spouse
   Details still shows the value. The surrounding spouse FD/MF/EQ handling (lines 422+) is unchanged.

## Contract / interface changes
None. No API, request/response, or React prop changes. `retirement_investments.epf` simply no longer
includes the spouse PF entry.

## Env / ports touched
Port **8001** (mapping runs there). No env var changes.

## Acceptance criteria & how to verify
1. For a client whose **spouse** has PF but whose own `pf_current_value` is empty: the Overview
   "Retirement Investments" table shows **no EPF row** (previously it showed the spouse's PF as EPF),
   while the **Spouse Details** tab still shows "Provident Fund (PF)" with the same value.
2. `GET :8001/clients/{record_id}` → `client_data.investment_details.retirement_investments.epf` no
   longer contains the spouse PF entry; `client_data.client_data.spouse.provident_fund` still does.
3. For a client where **both** the client and spouse have PF: the Overview EPF total drops by exactly
   the spouse PF amount; the portfolio pie / `totalInvestments` decrease accordingly.
4. `curl :8001/health` → `{"status":"ok"}`; `npm test` stays green.

## Tests
- **Backend unit test (recommended):** call `airtable_record_to_client_data(fields)` with a fixture
  that has spouse PF + no client PF; assert `retirement_investments.epf == []` and
  `client_data.spouse.provident_fund.current_value == <spouse value>`. A second fixture with both
  client + spouse PF asserts only the client's entry remains in `epf`.
- If no Python test path exists for `backend/`, mark **manual** and rely on acceptance #1/#2.

## Risks & rollback
- **Risk:** a client relied on the spouse PF being part of retirement EPF for their plan numbers —
  their retirement corpus will now be lower. This is the intended behavior per the user decision.
- **Rollback:** re-add the deleted block (revert the one-file change).

## Out of scope
- No change to Spouse Details rendering (`SpouseDetailsPanel.tsx`) — it already shows the value.
- No change to spouse MF/EQ/FD/ESOP handling (those intentionally still merge into client pools).
- Not relabeling "Provident Fund (PF)" → "EPF" under Spouse Details (the user chose show-only, not rename).

## Docs to update
`PROJECT_OVERVIEW.md` §7/§9 (or wherever the Airtable mapping is described): note that spouse PF is
shown under Spouse Details only and is **not** merged into the client's `retirement_investments.epf`.
