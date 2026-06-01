# Plan 0002 — User-entered Kid's Education target amount (inline + warning)

- **Status:** ready-for-execution
- **Branch / PR:** feat/education-target-user-input
- **Owner:** Claude Code (planner)

## Goal
Let the user type each child's education **target amount** (final corpus) **inline in the Education
Planning section**, and use that value as-is — no inflation — in the generated plan, instead of the
hardcoded pickle/default fee lookup. If a target is missing when the user clicks **Make plan**, show a
**warning pop-up** and block the run until it's entered.

## Context & rationale
Today the education "Target Amount" is derived, not entered:

- `backend/airtable_main.py` `airtable_record_to_client_data()` (lines 455–469) builds each child's
  `education_planning` row from Airtable (stream, destination, durations) but maps **no cost field**.
- `Financial_Planning/Nodes/child_education_nodes.py` `education_fees_calculation` (line 45) looks up
  `current_fees_of_graduation` / `current_fees_of_post_graduation` from
  `College_Fees_Scrapper/*.pkl` (fallback `education_fee_defaults.py`, hard floors ₹10L UG / ₹12L PG).
- `calculate_education_funding` (line 211) inflates that cost 6%/yr to the target year →
  `future_cost`. That `future_cost` is what surfaces as **"Target Amount"** in the UI
  (`components/EducationPlanningSection.tsx`, `stage.futureCost`, via
  `_build_education_planning_preview` → `ug_future_cost` / `pg_future_cost` in
  `backend/financial_plan_runner.py:221`).

**User decisions (confirmed, latest):**
1. The user enters the amount **inline in the Education Planning section** — the existing read-only
   "Target Amount" cell becomes an **editable input** per child (UG, and PG when a PG is planned).
2. The number is the **final target corpus** — used as-is, **no 6% inflation**.
3. The pop-up is a **warning only (no inputs)**. On **Make plan**, if any required target amount is
   blank, the pop-up tells the user to enter the value in the Education section, and the run is
   **blocked**. There is no silent default fallback — the user must enter it. (The node's lookup
   fallback stays only as a backend safety net; the UI enforces entry.)

**Why override `future_cost` specifically:** every downstream consumer keys off it —
`initial_gap = future_cost - total_future_corpus` (funding gap), `children_education_planning`'s
`target_corpus` (= `future_cost`), the education preview (`ug_future_cost`), and the education goals
that flow into `add_goals` → prioritization → allocation. Overriding `future_cost` makes the entered
value reflect everywhere with one surgical change, so `financial_plan_runner.py` and
`summarize_plan_state` need **no** changes. `current_cost` (the lookup estimate) is left intact as a
harmless fallback and is not shown in the education table.

**State flow:** the entered amounts must be readable by both the Education section (to edit) and the
Make-plan button (to validate + send), so the source of truth is a new state in `ClientsDashboard`,
passed down to both.

## Affected files
- `components/EducationPlanningSection.tsx` — **edit** (Target Amount cell → editable input; new props).
- `components/ClientsDashboard.tsx` — **edit** (hold `educationTargets` state; pass to Education section + FinancialPlanPanel; reset on client change).
- `components/FinancialPlanPanel.tsx` — **edit** (validate on Make plan; warning-only pop-up; send `education_targets`; new props).
- `app/api/financial-plan/run/route.ts` — **edit** (accept + forward `education_targets`).
- `backend/airtable_main.py` — **edit** (`FinancialPlanRequest` field; inject overrides into `education_planning` rows).
- `Financial_Planning/Nodes/child_education_nodes.py` — **edit** (`calculate_education_funding`: use override as `future_cost` when present).
- `PROJECT_OVERVIEW.md` — **edit** (docs sync — see "Docs to update").

`backend/financial_plan_runner.py` and `summarize_plan_state` are intentionally **unchanged**.
**No** dialog-with-inputs component is created (superseded by inline editing + warning-only pop-up).

## Implementation steps

### 1. `components/EducationPlanningSection.tsx` (edit)
Make the "Target Amount" cell an editable number input and lift its value via props.
- **Component props:** add
  ```ts
  targets: Record<string, { ug?: string; pg?: string }>;          // keyed by child name
  onTargetChange: (childName: string, side: "ug" | "pg", value: string) => void;
  ```
- **`StageTable` props:** extend to receive the editable binding:
  `{ stage, value, onChange }` where `value: string` and `onChange: (v: string) => void`.
- Replace the read-only Target Amount cell (currently `{fmtInr(stage.futureCost)}`) with a controlled
  input:
  ```tsx
  <td className={`${TD} text-right`}>
    <input
      type="number"
      min="0"
      inputMode="numeric"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="Enter amount"
      className="w-32 rounded border border-gray-300 bg-white px-2 py-1 text-right text-sm
                 text-gray-900 focus:border-brand focus:outline-none
                 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
    />
  </td>
  ```
- In the `EducationPlanningSection` body, pass the bindings to each `StageTable`:
  - UG: `value={targets[child.name]?.ug ?? ""}` `onChange={(v) => onTargetChange(child.name, "ug", v)}`
  - PG: `value={targets[child.name]?.pg ?? ""}` `onChange={(v) => onTargetChange(child.name, "pg", v)}`
- Keep Stream / Course Duration / Target Year columns exactly as they are. Update the JSDoc note above
  `StageTable` (currently says Target Amount = future_cost) to reflect that it is now a user input.
- **Do not show the post-plan "updated" figure here (request #2):** the Target Amount cell binds to the
  user's `educationTargets` value only. It must **not** be overwritten by the plan preview's
  `ug_future_cost` / `pg_future_cost` after Make plan. (The bound input already does this; just confirm
  `stage.futureCost` is no longer rendered in this cell and the preview value is not substituted in.)
  Stream / destination / target-year may still come from the preview; only the Target Amount stays the
  user-entered value.

### 2. `components/ClientsDashboard.tsx` (edit)
- **State (near line 470):**
  ```ts
  const [educationTargets, setEducationTargets] =
    useState<Record<string, { ug?: string; pg?: string }>>({});
  ```
- **Reset on client change:** in the `useEffect([selectedId])` (lines 482–489), add
  `setEducationTargets({});` alongside `setDetail(null)`.
- **Change handler:**
  ```ts
  const handleEduTargetChange = (childName: string, side: "ug" | "pg", value: string) =>
    setEducationTargets((prev) => ({
      ...prev,
      [childName]: { ...prev[childName], [side]: value },
    }));
  ```
- **Pass to the Education section** (line ~869):
  ```tsx
  <EducationPlanningSection
    blocks={educationBlocks}
    targets={educationTargets}
    onTargetChange={handleEduTargetChange}
  />
  ```
- **Pass to FinancialPlanPanel** (line ~689):
  ```tsx
  <FinancialPlanPanel
    recordId={selectedId}
    disabled={loadingDetail}
    onPlanResult={setPlanResult}
    educationBlocks={educationBlocks}
    educationTargets={educationTargets}
  />
  ```
  (`educationBlocks` already computed at line ~633.)

### 3. `components/FinancialPlanPanel.tsx` (edit)
- **Props:** add
  ```ts
  educationBlocks?: EducationChildBlock[];
  educationTargets?: Record<string, { ug?: string; pg?: string }>;
  ```
  (import `EducationChildBlock` from `@/lib/educationPlanningView`).
- **State:** `const [showWarning, setShowWarning] = React.useState(false);`
- **Helpers + click handler:**
  ```ts
  const parseAmt = (v?: string): number | null => {
    if (v == null || String(v).trim() === "") return null;
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? n : null;
  };
  const onMakePlanClick = () => {
    if (!recordId) return;
    const blocks = educationBlocks ?? [];
    const t = educationTargets ?? {};
    const missing = blocks.some(
      (b) =>
        parseAmt(t[b.name]?.ug) == null ||
        (b.hasPg && parseAmt(t[b.name]?.pg) == null),
    );
    if (missing) { setShowWarning(true); return; }          // block run, show warning
    const education_targets = blocks.map((b) => ({
      name_of_kid: b.name,
      ug_target_amount: parseAmt(t[b.name]?.ug),
      pg_target_amount: b.hasPg ? parseAmt(t[b.name]?.pg) : null,
    }));
    runPlan(education_targets.length ? education_targets : undefined);
  };
  ```
- **Button:** change the Make-plan button `onClick` (line ~530) from `runPlan` to `onMakePlanClick`.
- **`runPlan` signature:** change to accept the optional array and include it in the POST body:
  ```ts
  const runPlan = async (
    educationTargetsPayload?: Array<{ name_of_kid: string; ug_target_amount?: number | null; pg_target_amount?: number | null }>,
  ) => { ... body: JSON.stringify({ record_id: recordId, ...(educationTargetsPayload ? { education_targets: educationTargetsPayload } : {}) }), ... }
  ```
  (Rest of `runPlan` unchanged.)
- **Warning-only pop-up:** add a small modal component in this file (mirror the existing
  `PlanGeneratingOverlay` pattern — fixed inset, `role="dialog"`, `aria-modal`), e.g.
  `PlanWarningOverlay`, with the message **"Please enter the education target amount for each child in
  the Education Planning section before generating the plan."** and a single **OK** button that calls
  `onClose`. Render it when `showWarning` is true:
  ```tsx
  {showWarning ? <PlanWarningOverlay onClose={() => setShowWarning(false)} /> : null}
  ```
  No input fields in this overlay.

### 4. `app/api/financial-plan/run/route.ts` (edit)
Accept and forward the optional array. After parsing `record_id`:
```ts
const education_targets = Array.isArray(body?.education_targets) ? body.education_targets : undefined;
```
Forward only when defined:
```ts
body: JSON.stringify({ record_id, ...(education_targets ? { education_targets } : {}) }),
```
Keep the existing `record_id` required-field guard unchanged.

### 5. `backend/airtable_main.py` (edit)
- Extend the request model (lines 89–90):
  ```python
  class EducationTarget(BaseModel):
      name_of_kid: str
      ug_target_amount: float | None = None
      pg_target_amount: float | None = None

  class FinancialPlanRequest(BaseModel):
      record_id: str
      education_targets: list[EducationTarget] | None = None
  ```
- In `run_financial_plan` (lines 677–700), after `client_payload = airtable_record_to_client_data(fields)`
  (line 691) and **before** `run_financial_plan_for_client(client_payload)`, inject overrides onto the
  matching `education_planning` rows:
  ```python
  if req.education_targets:
      by_name = {t.name_of_kid: t for t in req.education_targets}
      for row in client_payload.get("education_planning", []):
          t = by_name.get(row.get("name_of_kid"))
          if not t:
              continue
          if t.ug_target_amount is not None:
              row["user_target_corpus_graduation"] = float(t.ug_target_amount)
          if t.pg_target_amount is not None:
              row["user_target_corpus_post_graduation"] = float(t.pg_target_amount)
  ```

### 6. `Financial_Planning/Nodes/child_education_nodes.py` (edit)
In `calculate_education_funding`, carry the override into each goal dict, then prefer it over inflation.
- UG goal append (lines 161–177), add: `"user_target_corpus": child.get("user_target_corpus_graduation"),`
- PG goal append (lines 182–198), add: `"user_target_corpus": child.get("user_target_corpus_post_graduation"),`
- Replace the `future_cost` line (211):
  ```python
  user_target = goal.get('user_target_corpus')
  if user_target is not None and float(user_target) > 0:
      future_cost = float(user_target)            # final target corpus, used as-is (no inflation)
  else:
      future_cost = calculate_future_value(goal['current_cost'], 0.06, goal['years_to_goal'])
  ```
No other lines change.

## Contract / interface changes
- **API:** `POST /api/financial-plan/run` and `POST :8001/financial-plan/run` body gains optional
  `education_targets`:
  ```json
  { "record_id": "rec123",
    "education_targets": [
      { "name_of_kid": "Aarav", "ug_target_amount": 5000000, "pg_target_amount": 8000000 }
    ] }
  ```
  Omitting it preserves current behavior. Response shape **unchanged**
  (`summary.education_planning_preview[].ug_future_cost` now equals the entered value).
- **Workflow state:** new optional per-child keys `user_target_corpus_graduation` /
  `user_target_corpus_post_graduation` on `education_planning` rows; transient goal key
  `user_target_corpus`. No new/removed nodes or edges.
- **React:** `EducationPlanningSection` gains `targets` + `onTargetChange`; `FinancialPlanPanel` gains
  `educationBlocks` + `educationTargets`; `ClientsDashboard` holds `educationTargets` state. New
  warning-only overlay inside `FinancialPlanPanel`.

## Env / ports touched
Ports **3000** (UI) and **8001** (data/plan API). No env var changes. A full Make-plan run still needs
`AZURE_API_*` for the LLM nodes; the education override itself uses no LLM.

## Acceptance criteria & how to verify
1. **Inline editing:** select a client with children → the Education Planning section shows an editable
   "Target Amount" input per child (UG, plus PG when planned). Typing updates the field.
2. **Warning blocks run:** leave any required target blank → click **Make plan** → a warning pop-up
   appears ("…enter the education target amount … in the Education Planning section…"), and **no**
   request is sent (Network shows no `POST /api/financial-plan/run`). Clicking OK dismisses it.
3. **Entered value used as-is:** fill all targets (e.g. UG `5000000`) → Make plan → request succeeds;
   in Plan review the education goal's corpus gap is computed against ₹50,00,000 and the entered value
   is **not** inflated; `summary.education_planning_preview[]` has `ug_future_cost == 5000000`.
4. **Backend contract:**
   ```
   curl -X POST http://localhost:8001/financial-plan/run \
     -H "Content-Type: application/json" \
     -d '{"record_id":"<rec>","education_targets":[{"name_of_kid":"<Kid>","ug_target_amount":5000000}]}'
   ```
   → that child's `ug_future_cost == 5000000`.
5. **No regression:** `curl :8001/health` → `{"status":"ok"}`; a client with **no children** runs Make
   plan with no warning and no `education_targets` (unchanged behavior); `npm test` stays green.
6. **Request #2 — entered value persists post-plan:** after a successful Make plan, the Education
   Planning "Target Amount" still shows the value the user typed (not a post-plan recomputed/updated
   figure); switching clients clears it.

## Tests
- **Node unit test (recommended):** `Financial_Planning/tests/test_education_funding_override.py` —
  state with one `education_planning` child carrying `user_target_corpus_graduation = 5_000_000` + a
  matching `children` DOB; call `calculate_education_funding(state)`; assert the child's UG entry in
  `state['client_data']['education_planning_summary']` has `future_cost == 5_000_000` (exact), and a
  control child without the key still inflates. No external services.
- **Frontend (optional):** RTL test that `FinancialPlanPanel` shows the warning and does **not** call
  `fetch` when a required target is blank, and that it posts `education_targets` when all are filled
  (mock `fetch`). RTL test that `EducationPlanningSection` renders a PG input only when `hasPg`.
- If a new pytest path is non-trivial here, mark the node test **manual** and rely on acceptance #3/#4.

## Risks & rollback
- **Risk:** required-field check too strict (e.g., a child with no PG planned should not require PG).
  Mitigated — PG is required only when `block.hasPg`.
- **Risk:** controlled-input state lost on client switch. Mitigated — `educationTargets` resets in the
  `selectedId` effect.
- **Risk:** `name_of_kid` mismatch between block and `education_planning` row drops the override. Both
  derive from the same Airtable `child_name`; the node falls back to lookup if unmatched.
- **Rollback:** revert the branch. Every layer is additive and optional (`education_targets` omitted →
  current behavior), so partial revert is safe.

## Out of scope
- No Airtable write-back / persistence of the entered amount (consistent with "no plan persistence" —
  values reset on client switch / refresh).
- No change to PG/UG duration or target-year logic (`education_target_years.py`).
- No change to the pickle/default fee tables or the `education_fees_calculation` lookup.
- No dialog with input fields (superseded); the pop-up is warning-only.

## Docs to update
`PROJECT_OVERVIEW.md`:
- §5.5 — `calculate_education_funding` now prefers a user-entered target corpus (no inflation) when
  provided, else falls back to inflated lookup.
- §11 (API surface) — add optional `education_targets` to `POST /financial-plan/run` and the Next proxy row.
- §7 (data flow) — note the inline-entered education target rides on `education_planning` rows into the workflow.
- §19/§23 — the ₹10L/₹12L hardcoded education amount is now entered inline by the user (required before Make plan).
