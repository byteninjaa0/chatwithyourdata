# Plan 0004 — Require user-entered EPF & PPF current values (inline + warning)

- **Status:** ready-for-execution
- **Branch / PR:** feat/require-epf-ppf-input
- **Owner:** Claude Code (planner)
- **Depends on:** Plan 0002 (reuses its `PlanWarningOverlay` + Make-plan validation pattern). Execute 0002 first.

## Goal
Make the client's **EPF** and **PPF** current values user-entered inline in the Overview retirement
table, and — exactly like the education target (plan 0002) — **block Make plan with a warning** if
either is left empty, instead of silently relying on whatever Airtable provides.

## Context & rationale
Today EPF/PPF current values come only from Airtable and render read-only:
- `backend/airtable_main.py:208–227` builds `epf_list` / `ppf_list` with `current_value` from
  `pf_current_value` / `ppf_current_value` (rates hardcoded 0.085 / 0.075).
- `components/ClientsDashboard.tsx:756–757` renders them in the Overview "Retirement Investments"
  table via the generic `DataTable` (`Type / Current Value / Contribution / Rate`).

**User decision (confirmed):** inline-edit the EPF and PPF **current value** in the Overview retirement
table; if either is empty when the user clicks Make plan, show the same blocking warning pop-up as the
education target. The entered values are used as the EPF/PPF current value in the plan run.

**Assumption (flag):** the inline fields are **pre-filled** from the Airtable value when present
(editable); an empty/zero value is what triggers the block. If you'd rather the fields always start
blank (ignore Airtable), say so and I'll revise.

**Constraint discovered:** the generic `DataTable` (`ClientsDashboard.tsx:133`) is typed
`Record<string, string | number>[]` and renders plain text — it cannot host `<input>` cells. So the
EPF/PPF rows must move to a small dedicated editable table; NPS stays in the generic `DataTable`.

**Scope:** only the **current value** of EPF and PPF is user-entered. Contributions and rates remain as
today. No workflow node changes — the retirement nodes already read `current_value` from the lists, so
overriding that value is sufficient.

## Affected files
- `components/RetirementInputsTable.tsx` — **create** (editable EPF/PPF current-value rows).
- `components/ClientsDashboard.tsx` — **edit** (hold `retirementInputs` state; render the editable table; pass values to `FinancialPlanPanel`; reset on client change).
- `components/FinancialPlanPanel.tsx` — **edit** (extend Make-plan validation + warning to EPF/PPF; send `retirement_overrides`).
- `app/api/financial-plan/run/route.ts` — **edit** (accept + forward `retirement_overrides`).
- `backend/airtable_main.py` — **edit** (`FinancialPlanRequest` fields; inject overrides into `epf_list` / `ppf_list`).
- `PROJECT_OVERVIEW.md` — **edit** (API + data-flow note).

`Financial_Planning/*` workflow nodes and `financial_plan_runner.py` are **unchanged**.

## Implementation steps

### 1. `components/RetirementInputsTable.tsx` (create)
A small table matching the Overview `DataTable` styling but with editable Current Value cells. Props:
```ts
{
  epf: { value: string; contribution: string; rate: string };   // contribution/rate display-only strings
  ppf: { value: string; contribution: string; rate: string };
  npsRows: Record<string, string | number>[];                   // pass-through for NPS (render read-only)
  onChange: (which: "epf" | "ppf", value: string) => void;
}
```
- Render columns `Type | Current Value | Contribution | Rate`.
- EPF and PPF "Current Value" cells are `<input type="number" min="0">` bound to `epf.value` / `ppf.value`,
  calling `onChange`. Placeholder `"Enter amount"`. Reuse the input className from plan 0002's
  `EducationPlanningSection` for visual consistency.
- NPS rows render as plain text (read-only), same as today.

### 2. `components/ClientsDashboard.tsx` (edit)
- **State (near line 470, alongside `educationTargets`):**
  ```ts
  const [retirementInputs, setRetirementInputs] = useState<{ epf: string; ppf: string }>({ epf: "", ppf: "" });
  ```
- **Pre-fill on detail load:** in the `useEffect([selectedId])` reset (lines 482–489) set
  `setRetirementInputs({ epf: "", ppf: "" });`. Then, once `detail` is available, pre-fill from the
  mapped values — add an effect keyed on `detail`:
  ```ts
  useEffect(() => {
    const epf0 = (ret?.epf ?? [])[0]?.current_value;
    const ppf0 = (ret?.ppf ?? [])[0]?.current_value;
    setRetirementInputs({
      epf: epf0 ? String(epf0) : "",
      ppf: ppf0 ? String(ppf0) : "",
    });
  }, [detail]);   // ret derives from detail
  ```
- **Change handler:**
  ```ts
  const handleRetInputChange = (which: "epf" | "ppf", value: string) =>
    setRetirementInputs((prev) => ({ ...prev, [which]: value }));
  ```
- **Replace** the EPF/PPF/NPS `DataTable` at lines 755–759 with `RetirementInputsTable`:
  ```tsx
  <RetirementInputsTable
    epf={{ value: retirementInputs.epf,
           contribution: `${inr((ret?.epf ?? [])[0]?.employee_employer_contribution_monthly ?? 0)} /mo`,
           rate: pct((ret?.epf ?? [])[0]?.interest_rate ?? 0.085) }}
    ppf={{ value: retirementInputs.ppf,
           contribution: `${inr((ret?.ppf ?? [])[0]?.annual_contribution ?? 0)} /yr`,
           rate: pct((ret?.ppf ?? [])[0]?.interest_rate ?? 0.075) }}
    npsRows={(ret?.nps ?? []).map(x => ({ Type: "NPS", "Current Value": inr(x.current_value), "Contribution": `${inr(x.monthly_contribution)} /mo`, "Rate": "—" }))}
    onChange={handleRetInputChange}
  />
  ```
- **Pass to FinancialPlanPanel** (line ~689) alongside the education props from plan 0002:
  ```tsx
  retirementInputs={retirementInputs}
  ```

### 3. `components/FinancialPlanPanel.tsx` (edit)
- **Props:** add `retirementInputs?: { epf: string; ppf: string };`
- **Validation in `onMakePlanClick`** (the handler added in plan 0002): extend the missing-check so it
  also fails when EPF or PPF is blank/≤0, reusing the `parseAmt` helper:
  ```ts
  const ri = retirementInputs ?? { epf: "", ppf: "" };
  const retMissing = parseAmt(ri.epf) == null || parseAmt(ri.ppf) == null;
  if (missing || retMissing) { setShowWarning(true); return; }   // same warning overlay as education
  ```
- **Build the override** and include it in the `runPlan` call:
  ```ts
  const retirement_overrides = {
    epf_current_value: parseAmt(ri.epf),
    ppf_current_value: parseAmt(ri.ppf),
  };
  runPlan(education_targets.length ? education_targets : undefined, retirement_overrides);
  ```
- **`runPlan` signature:** add a second optional arg and include it in the POST body when present:
  ```ts
  const runPlan = async (educationTargetsPayload?, retirementOverrides?) => {
    ... body: JSON.stringify({
      record_id: recordId,
      ...(educationTargetsPayload ? { education_targets: educationTargetsPayload } : {}),
      ...(retirementOverrides ? { retirement_overrides: retirementOverrides } : {}),
    }), ...
  }
  ```
- **Warning copy:** update the `PlanWarningOverlay` message (from plan 0002) to cover both, e.g.
  "Please enter the education target amounts and the EPF & PPF current values before generating the plan."

### 4. `app/api/financial-plan/run/route.ts` (edit)
After parsing `record_id` (and `education_targets` from plan 0002):
```ts
const retirement_overrides =
  body?.retirement_overrides && typeof body.retirement_overrides === "object"
    ? body.retirement_overrides
    : undefined;
```
Forward it only when defined:
```ts
body: JSON.stringify({ record_id, ...(education_targets ? { education_targets } : {}), ...(retirement_overrides ? { retirement_overrides } : {}) }),
```

### 5. `backend/airtable_main.py` (edit)
- Extend the request model (the `FinancialPlanRequest` from plan 0002):
  ```python
  class RetirementOverrides(BaseModel):
      epf_current_value: float | None = None
      ppf_current_value: float | None = None

  class FinancialPlanRequest(BaseModel):
      record_id: str
      education_targets: list[EducationTarget] | None = None       # from plan 0002
      retirement_overrides: RetirementOverrides | None = None
  ```
- In `run_financial_plan` (after `client_payload = airtable_record_to_client_data(fields)`, near the
  education injection from plan 0002), inject the EPF/PPF current values:
  ```python
  ro = req.retirement_overrides
  if ro:
      ret = client_payload.get("investment_details", {}).get("retirement_investments", {})
      if ro.epf_current_value is not None:
          epf = ret.setdefault("epf", [])
          if epf:
              epf[0]["current_value"] = float(ro.epf_current_value)
          else:
              epf.append({"current_value": float(ro.epf_current_value),
                          "employee_employer_contribution_monthly": 0, "interest_rate": 0.085})
      if ro.ppf_current_value is not None:
          ppf = ret.setdefault("ppf", [])
          if ppf:
              ppf[0]["current_value"] = float(ro.ppf_current_value)
          else:
              ppf.append({"current_value": float(ro.ppf_current_value),
                          "annual_contribution": 0, "interest_rate": 0.075})
  ```

No workflow node edits — the retirement nodes consume `current_value` from these lists.

## Contract / interface changes
- **API:** `POST /api/financial-plan/run` and `POST :8001/financial-plan/run` body gains optional
  `retirement_overrides`:
  ```json
  { "record_id": "rec123",
    "education_targets": [ ... ],
    "retirement_overrides": { "epf_current_value": 1500000, "ppf_current_value": 800000 } }
  ```
  Omitting it preserves current behavior. Response shape unchanged.
- **React:** `ClientsDashboard` holds `retirementInputs`; `FinancialPlanPanel` gains `retirementInputs`;
  new `RetirementInputsTable` component; the Overview EPF/PPF cells become inputs.

## Env / ports touched
Ports **3000** (UI) and **8001** (data/plan API). No env var changes. A full Make-plan run still needs
`AZURE_API_*` for the LLM nodes.

## Acceptance criteria & how to verify
1. **Inline editing:** Overview → Retirement Investments shows editable EPF and PPF "Current Value"
   inputs (NPS stays read-only). Pre-filled from Airtable when present.
2. **Warning blocks run:** clear the EPF (or PPF) input → click Make plan → the same warning pop-up
   appears and **no** `POST /api/financial-plan/run` is sent.
3. **Entered value used:** set EPF `1500000`, PPF `800000`, fill education targets → Make plan succeeds;
   the plan's retirement corpus reflects the entered EPF/PPF (not the original Airtable values).
4. **Backend contract:**
   ```
   curl -X POST http://localhost:8001/financial-plan/run \
     -H "Content-Type: application/json" \
     -d '{"record_id":"<rec>","education_targets":[...],"retirement_overrides":{"epf_current_value":1500000,"ppf_current_value":800000}}'
   ```
   returns `{ ok: true, ... }` and the run uses the supplied values.
5. **No regression:** `curl :8001/health` → ok; `npm test` stays green.

## Tests
- **Frontend (recommended):** RTL test that `FinancialPlanPanel` shows the warning and does not call
  `fetch` when EPF/PPF is blank, and posts `retirement_overrides` when filled (mock `fetch`).
- **Backend (recommended):** unit test that `run_financial_plan` injection sets
  `retirement_investments.epf[0].current_value` from `retirement_overrides` (mock Airtable + the
  workflow runner so no Azure call).
- Otherwise mark **manual** and rely on acceptance #2–#4.

## Risks & rollback
- **Risk:** validation conflicts with clients who have no PPF at all. Per the user decision EPF **and**
  PPF are both required; a client without PPF must enter a value (or 0 is rejected). If that's too
  strict, revisit — flagged.
- **Risk:** `RetirementInputsTable` styling drifts from the generic `DataTable`. Mitigated by reusing
  the same className strings.
- **Rollback:** revert the branch; with `retirement_overrides` omitted the backend behaves exactly as today.

## Out of scope
- EPF/PPF **contribution** and **rate** stay as today (only current value is user-entered).
- No persistence of entered values (reset on client switch/refresh — consistent with the repo).
- No change to NPS, ULIP, or other retirement schemes.
- Spouse PF handling is plan 0003, not this plan.

## Docs to update
`PROJECT_OVERVIEW.md`:
- §11 (API surface) — add optional `retirement_overrides` to `POST /financial-plan/run` + Next proxy row.
- §7 (data flow) — EPF/PPF current values can be user-entered inline and override the Airtable values at run time.
- §10/§19 — EPF/PPF current value is now a required user input before Make plan (was Airtable-only, rates still hardcoded).
