# Project Overview

Technical reference for the repo as it exists today. Claims below were checked against source files, not aspirational design docs. **There is no `agent/planner/` tree** — the financial planning workflow lives under `Financial_Planning/` and is invoked over HTTP from the Airtable FastAPI service, not from the Copilot chat agent.

---

## 1. What this project does

Users see a **financial planning dashboard** with a client list, per-client portfolio/net-worth views (Airtable → Python API → Next.js), a **Make plan** control that runs a **20-node LangGraph pipeline** (`Financial_Planning/Workflow/workflow.py`), and a **Copilot sidebar** for natural-language Q&A.

Two separate AI/runtime paths:

| Path | Trigger | Runtime | Purpose |
|------|---------|---------|---------|
| **Chat** | Copilot sidebar message | `agent/main.py` (default) or Next.js direct Azure | Answer questions using dashboard readables + optional Tavily search |
| **Financial plan** | **Make plan** button in `FinancialPlanPanel` | `backend/airtable_main.py` → `financial_plan_runner.py` → `run_financial_plan_workflow()` | Deterministic-ish pipeline: mostly fixed node order, two LLM nodes, numeric allocation math |

The chat agent **cannot** invoke the planning workflow (no tool, no subgraph, no shared endpoint). After Make plan, the compact `summary` is held in React state and exposed to the chat via `useCopilotReadable` — the model can *read* plan output but not *run* it.

---

## 2. Tech stack

### Frontend

| Package | Declared (`package.json`) | Lockfile (`package-lock.json`) |
|---------|---------------------------|--------------------------------|
| Next.js | `^15.5.18` | `15.5.18` |
| React / react-dom | `^19.0.0` | `19.2.6` |
| CopilotKit (`react-core`, `react-ui`, `runtime`) | `^1.57.1` | `1.57.1` |
| Vercel AI SDK (`ai`, `@ai-sdk/openai`) | `^6.0.104`, `^3.0.36` | (resolved in lockfile) |
| Tailwind | `^4` | — |
| recharts | `^2.15.1` | — |
| `@tavily/core` | `^0.3.1` | Direct-Azure chat path only |

**Declared but unused in app source:** `@tremor/react`, `@hookform/resolvers`, `react-hook-form`, `react-day-picker`, `zod` (no imports under `app/`, `components/`, `lib/`).

### Chat agent (`agent/`)

| Package | `agent/requirements.txt` |
|---------|--------------------------|
| fastapi, uvicorn | `>=0.115.0`, `>=0.32.0` |
| copilotkit, ag-ui-langgraph | `>=0.1.89`, `>=0.0.35` |
| langgraph, langchain, langchain-openai | `>=0.4.0`, `>=1.0.0`, `>=0.3.0` |
| tavily-python, python-dotenv | `>=0.5.0`, `>=1.0.0` |

Python version is **not pinned** in-repo; LangChain 1.x typically needs 3.10+.

### Financial data + planning API (`backend/`)

| Package | `backend/requirements.txt` |
|---------|----------------------------|
| fastapi, uvicorn, requests, python-dotenv | as above |
| pandas, pyarrow, yfinance | RSU market cache |
| langgraph, langchain, langchain-openai, langchain-community, langchain-core | planning workflow |
| babel, numpy | workflow dependencies |

### Providers

- **Azure OpenAI** — chat agent: `AZURE_OPENAI_*` (aliases `AZURE_API_*` in `agent/main.py`); planning LLM nodes: `AZURE_API_*` in `Financial_Planning/Nodes/agentic_nodes.py`; direct Next chat: `AZURE_API_*` in `app/api/copilotkit/route.ts`
- **Tavily** — `searchInternet` in chat; `tavily_tool` in `Financial_Planning/Toools/standard_tools.py` (used by fee scrapper script, not the main workflow graph)
- **Airtable** — client records via `backend/airtable_main.py`

---

## 3. Architecture diagram

```
┌─────────────┐
│    User     │
└──────┬──────┘
       │
       ├─────────────────────────────────────────────────────────────┐
       │ Dashboard (React)                                         │ Sidebar chat
       ▼                                                             ▼
┌──────────────────────────────┐                    ┌──────────────────────────────┐
│ ClientsDashboard             │                    │ CopilotSidebar + CopilotKit  │
│ FinancialPlanPanel           │                    │ useCopilotReadable / Action  │
│  "Make plan" button          │                    │ runtimeUrl=/api/copilotkit   │
└──────────┬───────────────────┘                    └──────────────┬───────────────┘
           │ POST /api/financial-plan/run                           │ CopilotKit HTTP
           ▼                                                       ▼
┌──────────────────────────────┐                    ┌──────────────────────────────┐
│ Next.js API routes           │                    │ app/api/copilotkit/route.ts  │
│ (proxy → :8001)              │                    │  LangGraphHttpAgent OR       │
└──────────┬───────────────────┘                    │  OpenAIAdapter (direct)      │
           │ HTTP JSON                                └──────────────┬───────────────┘
           ▼                                                       │
┌──────────────────────────────┐                    ┌──────────────▼───────────────┐
│ FastAPI :8001                │                    │ LangGraph agent :8000        │
│ backend/airtable_main.py     │                    │ agent/main.py                │
│  GET /clients, /clients/{id}│                    │  POST /copilotkit            │
│  POST /financial-plan/run ───┼──► NOT connected   │  AG-UI SSE (EventEncoder)    │
│       │                      │    to chat agent   │  create_agent() ReAct loop   │
│       ▼                      │                    │  tool: searchInternet only   │
│ financial_plan_runner.py     │                    └──────────────┬───────────────┘
│  chdir(repo_root)            │                                   │ HTTPS
│  run_financial_plan_workflow │                                   ▼
│       ▼                      │                              Azure OpenAI
│ Financial_Planning/          │
│  Workflow/workflow.py        │
│  (20-node StateGraph)        │──► Azure OpenAI (risk + goal_prioritization nodes)
│       │                      │──► pickle fee tables, RSU parquet, utility math
│       ▼                      │
│  returns { ok, summary }     │  (full state discarded; summary only to UI)
└──────────────────────────────┘
           │
           ▼ HTTP
      Airtable REST API
```

**How the planner is wired:** **Separate HTTP endpoint**, not a Copilot tool, not a subgraph of `dashboard_agent`, not AG-UI. Invocation chain: `FinancialPlanPanel.runPlan()` → `POST /api/financial-plan/run` → `POST /financial-plan/run` on port 8001 → `run_financial_plan_for_client()`.

**Protocols by boundary**

| Boundary | Protocol |
|----------|----------|
| Browser ↔ Next.js | HTTP (JSON) |
| `CopilotSidebar` ↔ `/api/copilotkit` | CopilotKit runtime (HTTP POST + streaming) |
| Next `/api/copilotkit` ↔ Python `:8000/copilotkit` | HTTP POST + **AG-UI SSE** |
| Chat agent ↔ Azure OpenAI | HTTPS (Azure Chat Completions) |
| Make plan ↔ FastAPI `:8001` | HTTP JSON request/response (no SSE) |
| FastAPI ↔ Airtable | HTTPS REST |
| Planning LLM nodes ↔ Azure | HTTPS (`AZURE_API_*` in `agentic_nodes.py`) |

---

## 4. Request lifecycle — chat (Copilot sidebar)

**Assumption:** `LANGGRAPH_AGENT_URL` is set (recommended in `.env.example`).

1. User submits in `CopilotSidebar` (`app/page.tsx`).
2. `<CopilotKit runtimeUrl="/api/copilotkit" agent="dashboard_agent">` (`app/layout.tsx`) POSTs to Next.
3. `app/api/copilotkit/route.ts` → `LangGraphHttpAgent` → `http://localhost:8000/copilotkit`.
4. `agent/main.py` `langgraph_agent_endpoint()` streams **AG-UI SSE** via `EventEncoder`.
5. `LangGraphAGUIAgent.run()` drives `build_graph()` → `langchain.agents.create_agent()` with `CopilotKitMiddleware`, `MemorySaver`, `searchInternet`.
6. Tool `searchInternet` → Tavily (`tavily-python`).
7. Frontend `useCopilotAction({ name: "searchInternet", available: "disabled" })` in `ClientsDashboard.tsx` only renders `SearchResults` — execution is server-side.
8. Stream completes; turn ends.

**Direct Azure path** (`LANGGRAPH_AGENT_URL` unset): steps 3–5 use `createDirectLlmRuntime()` + `OpenAIAdapter`; Tavily runs in `route.ts` `handler` via `@tavily/core`.

---

## 5. Financial planning workflow

**Source of truth:** `Financial_Planning/Workflow/workflow.py` — `graph = StateGraph(ClientState)`, compiled as `workflow = graph.compile()`.

### 5.1 Trigger and persistence

| Step | Implementation |
|------|----------------|
| UI | `components/FinancialPlanPanel.tsx` — **Generate Financial Plan** / Make plan; `POST` body `{ record_id }` |
| Next proxy | `app/api/financial-plan/run/route.ts` |
| Backend | `backend/airtable_main.py` `run_financial_plan()` — re-fetches Airtable record, `airtable_record_to_client_data()`, then `run_financial_plan_for_client()` |
| Runner | `backend/financial_plan_runner.py` — `os.chdir(REPO_ROOT)`, `workflow.invoke(...)`, `summarize_plan_state()` |
| Response | `{ "ok": true, "summary": { ... } }` — **not** full LangGraph state |
| Stored where | **Browser React state only** (`planResult` in `ClientsDashboard` via `onPlanResult`). Lost on refresh. **No DB, no Airtable write-back.** |
| Chat visibility | `useCopilotReadable` exposes `plan_summary` when `generated: true` (`components/ClientsDashboard.tsx`) |

### 5.2 State object (`ClientState`)

Defined in `Financial_Planning/Models/client_data_state.py` as a `TypedDict`.

**Initial state** (`run_financial_plan_workflow` in `workflow.py`):

```python
{
    "client_data": client_data,      # nested payload from Airtable mapper
    "EMI_allocated": False,
    "loan_prepayed_times": 0,
    "used_monthly_surplus": [0],
    "optimal_selected": False,
}
```

**Merge semantics:** LangGraph merges each node's return dict into state. Several fields use `Annotated[..., add]` (list/reducer append): `goal_funding`, `liability_allocation`, `used_monthly_surplus`, `used_liquid_surplus`, `freed_timeline`, `unused_monthly_surplus`. Most other keys are last-write wins.

**Input shape:** `client_data` matches Armstrong layout: top-level keys `client_data`, `investment_details`, `financial_goals`, `liabilities`, `education_planning`, `life_insurance` — built by `airtable_record_to_client_data()` in `backend/airtable_main.py`.

### 5.3 Node list and DAG (actual edges)

**20 active nodes** (emergency-fund node is commented out in `workflow.py` lines 58–59).

```
START
  → calculate_age
  → calculate_retirement_corpus
  → calculate_all_retirement_investments
  → retirement_goal
  → [conditional: check_for_kid]
        True  → education_fees_calculation → calculate_education_funding → goals_future_value
        False → goals_future_value
  → add_goals
  → update_ulip_current_values
  → asset_basket_classification
  → risk_appetite_assessment          ← LLM
  → calculate_liquid_asset_value
  → calculate_fixed_assets_value
  → calculate_asset_percentages_and_ratios
  → goal_prioritization               ← LLM
  → freed_emi_by_year
  → plan_goals
  → [conditional: check_for_pre_payment]
        True  → plan_prepayments ──(loop back)──► plan_goals
        False → choose_optimal_strategy
  → choose_optimal_strategy (when routed from plan_goals)
  → invest_monthly_surplus
  → END
```

**Conditional edges**

| From | Router | `True` | `False` | Notes |
|------|--------|--------|---------|-------|
| `retirement_goal` | `check_for_kid` | `education_fees_calculation` | `goals_future_value` | Reads `state['client_data']['client_data']['if_any_kids']` |
| `plan_goals` | `check_for_pre_payment` | `plan_prepayments` | `choose_optimal_strategy` | Map also lists `'END': END` but **`check_for_pre_payment` only returns `True` or `False`** — `END` branch is dead |

**Prepayment loop:** `plan_prepayments` → `plan_goals` again. `check_for_pre_payment` (`basic_calculations_nodes.py`) loops while EMI prepayment flag set, interest-saved delta ≥ ₹500, and iteration count &lt; 8; special cases stop early when no liquid pool for lump-sum prepay.

### 5.4 Determinism

- **Topology:** Fixed `add_edge` / conditional routes above — not LLM-chosen node order.
- **Deterministic nodes:** Age, retirement FV, education fees from pickle tables, asset buckets, liquid/fixed pools, ratios, `freed_emi_by_year`, `plan_goals`, `plan_prepayments`, `choose_optimal_strategy`, `invest_monthly_surplus`, most of `goals_future_value` / `add_goals`.
- **Non-deterministic nodes:** `risk_appetite_assessment`, `goal_prioritization` — Azure LLM + tools, then `with_structured_output` parsing (`agentic_nodes.py`, `temperature=0` on deployment but still model variance).
- **Guarantee:** Order is enforced by compiled LangGraph edges, not by prompts.

### 5.5 Per-node behavior (math vs stub)

| Node | File | Implemented? | What it does |
|------|------|--------------|--------------|
| `calculate_age` | `basic_calculations_nodes.py` | Yes | Year-diff ages; `monthly_surplus` = salary + other income − expenses − vacation/12 − misc kids (EMIs **not** subtracted here) |
| `calculate_retirement_corpus` | `retirement_nodes.py` | Yes | Inflation 6%, real return 4%, life expectancy 85; standard PV annuity + phased lifestyle segments |
| `calculate_all_retirement_investments` | `retirement_nodes.py` | Yes | EPF/PPF/NPS/ULIP FV via `utility_functions` |
| `retirement_goal` | `retirement_nodes.py` | Yes | Corpus gap vs scheme grand total; emits retirement goal row |
| `education_fees_calculation` | `child_education_nodes.py` | Yes (lookup) | Fees from **pickle defaults** (`College_Fees_Scrapper/*.pkl`) or hardcoded fallbacks (₹10L UG / ₹12L PG) — **not** live `education_fees_scrapper.py` in this graph |
| `calculate_education_funding` | `child_education_nodes.py` | Yes | FV education costs, SSY/scheme usage, SIP gaps per child goal |
| `goals_future_value` | `goal_consolidation_nodes.py` | Yes | Saved amount @ 9%, capital @ 6% inflation; surplus cascade between goals |
| `add_goals` | `goal_consolidation_nodes.py` | Yes | Merges financial + education + retirement goals; may inject post-retirement loan-closure goals |
| `update_ulip_current_values` | `basic_calculations_nodes.py` | Yes | ULIP XIRR bisection, opportunity-cost vs equity/BAF benchmarks |
| `asset_basket_classification` | `basic_calculations_nodes.py` | Yes | Tags assets liquid / fixed / retirement with IDs |
| `risk_appetite_assessment` | `agentic_nodes.py` | LLM | `Agent` + `risk_analysis` tool → structured `RiskSchema` |
| `calculate_liquid_asset_value` | `basic_calculations_nodes.py` | Yes | Sums liquid basket |
| `calculate_fixed_assets_value` | `basic_calculations_nodes.py` | Yes | Sums fixed basket |
| `calculate_asset_percentages_and_ratios` | `basic_calculations_nodes.py` | Yes | Liquidity ratio, flexibility, spending behavior heuristics |
| `goal_prioritization` | `agentic_nodes.py` | LLM | Tools `calculate_priority_score`, `sort_goals_by_priority` → `PrioritizedGoals`; post-process `sip_required` @ 9% |
| `freed_emi_by_year` | `basic_calculations_nodes.py` | Yes | Natural loan amortization timeline |
| `plan_goals` | `allocations_nodes.py` | Yes | Greedy allocation: lumpsum, freed SIP, surplus SIP to sorted goals; can set `EMI_allocation` for prepay path |
| `plan_prepayments` | `allocations_nodes.py` | Yes | Loan prepayment optimizer (uses `loan_prepayment_consolidated` logic) |
| `choose_optimal_strategy` | `allocations_nodes.py` | Yes | Picks best among allocation scenarios (surplus + interest saved) |
| `invest_monthly_surplus` | `basic_calculations_nodes.py` | Yes | Leftover surplus → 30% debt / 40% hybrid / 30% equity |
| `check_and_allocate_emergency_fund` | `basic_calculations_nodes.py` | **Not in graph** | Implementation exists but commented out in `workflow.py` |

**Nested agent graphs (inside two nodes):** `Financial_Planning/Agent/agent.py` — small ReAct loop (`llm` ↔ `action`) used only inside `risk_appetite_assessment` and `goal_prioritization`, not exposed to CopilotKit.

### 5.6 PPT generator (not in dashboard path)

`Financial_Planning/Main/main.py` runs the same `workflow` against persona fixtures and fills PowerPoint templates — **not** called from `backend/airtable_main.py` or the Next app.

---

## 6. How the two agents interact

**Framing:** This is **not** a multi-agent orchestration system in the Copilot/LangGraph sense. It is:

1. **`dashboard_agent`** — one ReAct chat loop (`agent/main.py`, `create_agent`), tools = `[searchInternet]`, state = conversation + CopilotKit readables, `MemorySaver` checkpointing in-process.
2. **Financial planning workflow** — separate compiled `StateGraph`, invoked synchronously over HTTP, no shared thread ID with chat.

**Coupling:** One-way, UI-mediated:

- User runs Make plan → `summary` JSON in React state.
- `useCopilotReadable` passes `plan_summary` to CopilotKit so chat can answer *about* the plan.
- Chat cannot re-run or mutate the plan; stale if user changes Airtable data without re-running Make plan.

**No** `run_financial_plan` tool in `agent/main.py` (verified: no matches under `agent/`).

---

## 7. Data flow and state management

```
Airtable record
    → GET /clients/{id} (dashboard load, cached in React `detail`)
    → POST /financial-plan/run (re-fetch same record_id at run time)
    → airtable_record_to_client_data()  (field mapping, hardcoded rates e.g. EPF 8.5%)
    → workflow.invoke(initial_state)
    → summarize_plan_state(full_state)  (~20 goal rows max in previews)
    → FinancialPlanPanel UI + useCopilotReadable
```

| Concern | Current behavior |
|---------|------------------|
| Source of truth for inputs | Airtable (read-only in app) |
| Plan persistence | None server-side; refresh loses plan |
| Chat thread persistence | `MemorySaver` in agent process only; lost on agent restart |
| Concurrency | No locking; two simultaneous Make plan runs for same client = two independent invokes, last UI write wins |
| Stale plan in chat | Readable still shows old `plan_summary` if Airtable data changed but Make plan not re-run |
| RSU prices | `backend/data/rsu_market_data.parquet` (optional); refresh via `/rsu-refresh` — used in allocation nodes when RSU present |

---

## 8. Modes: LangGraph chat vs Direct Azure chat

| | **LangGraph mode** | **Direct Azure mode** |
|---|-------------------|----------------------|
| **Toggle** | `LANGGRAPH_AGENT_URL` non-empty | unset / empty |
| **Checked in** | `app/api/copilotkit/route.ts`, `app/layout.tsx` |
| **Runtime** | `LangGraphHttpAgent` → `:8000/copilotkit` | `OpenAIAdapter` in Next |
| **LLM env** | `AZURE_OPENAI_*` in Python `.env` | `AZURE_API_*` or `OPENAI_API_KEY` in Next |
| **Tools** | Python `@tool("searchInternet")` | `CopilotRuntime` actions in `route.ts` |
| **Make plan** | Unaffected — always needs `:8001` + `backend/requirements.txt` | Same |

**Make plan** does not use `LANGGRAPH_AGENT_URL`; it only needs the FastAPI backend with LangGraph stack installed.

---

## 9. Files inventory

### Application shell

| File | Role |
|------|------|
| `app/layout.tsx` | `CopilotKit` provider, optional `agent="dashboard_agent"` |
| `app/page.tsx` | `CopilotSidebar`, clock readable, `ClientsDashboard` |
| `app/globals.css` | Tailwind v4 + CopilotKit CSS vars |
| `app/api/copilotkit/route.ts` | Chat runtime proxy or direct Azure |
| `app/api/airtable/clients/route.ts` | `GET` → FastAPI `/clients` |
| `app/api/airtable/clients/[id]/route.ts` | `GET` → FastAPI `/clients/{id}` |
| `app/api/financial-plan/run/route.ts` | `POST { record_id }` → `/financial-plan/run` |
| `app/api/rsu-market-data/route.ts` | `GET` → `/rsu-market-data` |
| `app/api/rsu-refresh/route.ts` | RSU cache refresh proxy |
| `app/api/rsu/market-data/route.ts` | Legacy RSU paths |
| `components/ClientsDashboard.tsx` | Main dashboard, readables, `FinancialPlanPanel` |
| `components/FinancialPlanPanel.tsx` | Make plan UI + summary tables |
| `components/AssistantMessage.tsx` | Markdown + tool `subComponent` |
| `components/generative-ui/SearchResults.tsx` | Search tool status UI |
| `components/Dashboard.tsx` | **Unused** demo dashboard |
| `components/Header.tsx`, `Footer.tsx` | Static chrome |
| `components/ui/*` | shadcn-style primitives + charts |
| `lib/prompt.ts` | Copilot instructions (plan vs input data) |
| `lib/fastapi-proxy.ts` | Shared FastAPI `fetch` helper |
| `lib/utils.ts` | `cn()` |
| `lib/user-info.ts` | **Dead** — not imported |
| `data/dashboard-data.ts` | Demo data for unused `Dashboard.tsx` |
| `next.config.ts` | `allowedDevOrigins`, standalone trace root |

### Chat agent

| File | Role |
|------|------|
| `agent/main.py` | FastAPI AG-UI server, `dashboard_agent`, `searchInternet` |
| `agent/requirements.txt` | Chat agent dependencies |

### Backend API

| File | Role |
|------|------|
| `backend/airtable_main.py` | Airtable CRUD mapping, `/financial-plan/run`, RSU routes |
| `backend/financial_plan_runner.py` | Invoke workflow, build `summary` |
| `backend/rsu_market.py` | Parquet RSU/FX cache |
| `backend/stdio_utf8.py` | Windows UTF-8 stdout fix |
| `backend/requirements.txt` | FastAPI + planning stack |

### Financial planning package (`Financial_Planning/`)

| File | Role |
|------|------|
| `Workflow/workflow.py` | **Graph definition**, `run_financial_plan_workflow()` |
| `Workflow/__init__.py` | Package marker |
| `Models/client_data_state.py` | `ClientState`, `AgentState` |
| `Models/llm_schemas.py` | Pydantic schemas for structured LLM outputs |
| `Models/test.py` | Test/scratch (not wired to app) |
| `Nodes/basic_calculations_nodes.py` | Age, ULIP, baskets, ratios, surplus invest, EMI freed, routers |
| `Nodes/retirement_nodes.py` | Corpus, scheme FV, retirement goal |
| `Nodes/child_education_nodes.py` | Education fees + funding |
| `Nodes/goal_consolidation_nodes.py` | Goal FV, `add_goals` |
| `Nodes/allocations_nodes.py` | `plan_goals`, `plan_prepayments`, `choose_optimal_strategy` |
| `Nodes/agentic_nodes.py` | LLM risk + prioritization |
| `Agent/agent.py` | Inner ReAct agent for LLM nodes |
| `Toools/custom_tools.py` | LangChain tools for prioritization / risk |
| `Toools/standard_tools.py` | Tavily tool (scrapper script) |
| `Utilities/utility_functions.py` | FV, SIP, loan math, allocation helpers |
| `Utilities/prompts.py` | LLM system prompts |
| `Utilities/ppt_utilities.py`, `ppt_builder.py` | PPT generation helpers |
| `RSU/webscrapper.py` | RSU parquet load + refresh |
| `College_Fees_Scrapper/education_fees_scrapper.py` | Standalone fee scraper (not in workflow graph) |
| `College_Fees_Scrapper/*.pkl` | Cached fee tables used by workflow |
| `education_fee_defaults.py` | Python defaults if pickle missing |
| `loan_prepayment_consolidated.py` | Prepayment planning core |
| `input_data.py`, `input_data_personas.py` | Sample / persona payloads |
| `Main/main.py` | Standalone PPT pipeline (not dashboard) |
| `PPT_io/PPT_template/*.pptx` | PowerPoint templates |

**Not present:** `agent/planner/` (no `graph.py`, `tools.py`, or planner store in this repo).

---

## 10. Environment variables

| Variable | Required for | Purpose |
|----------|--------------|---------|
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT_NAME` | Chat agent (LangGraph mode) | Python agent LLM |
| `OPENAI_API_VERSION` / `AZURE_API_VERSION` | Chat agent | Azure API version |
| `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_DEPLOYMENT_NAME` | Make plan LLM nodes, direct Next chat | `agentic_nodes.py`, `route.ts` |
| `OPENAI_API_KEY` | Direct Next chat | Fallback if no Azure |
| `TAVILY_API_KEY` | `searchInternet`, optional scrapper | Web search |
| `LANGGRAPH_AGENT_URL` | LangGraph chat mode | Default `http://localhost:8000/copilotkit` |
| `LANGGRAPH_AGENT_PORT` | Chat agent bind | Default `8000` |
| `NEXT_PUBLIC_LANGGRAPH_AGENT_ID` | CopilotKit | Must match `dashboard_agent` |
| `FASTAPI_BASE_URL`, `FASTAPI_PORT` | Dashboard + proxies | Default `8001` |
| `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE`, `AIRTABLE_TOKEN` | Client data | Airtable PAT |
| `NODE_ENV=production` | `next build` | Standard Next |

Repo-root `.env` is loaded by `agent/main.py`, `backend/airtable_main.py`, and planning modules via `python-dotenv`.

---

## 11. API surface

### Next.js (`app/api/`)

| Method | Path | Body / params | Response | Upstream |
|--------|------|---------------|----------|----------|
| `GET` | `/api/copilotkit` | — | `{ mode, agents?, langGraphAgentUrl? }` | Local |
| `POST` | `/api/copilotkit` | CopilotKit run payload | SSE (LangGraph) or adapter stream | `:8000` or Azure |
| `GET` | `/api/airtable/clients` | — | `{ clients: [{ record_id, name }] }` | `GET :8001/clients` |
| `GET` | `/api/airtable/clients/[id]` | — | `{ record_id, client_data: {...} }` | `GET :8001/clients/{id}` |
| `POST` | `/api/financial-plan/run` | `{ record_id: string }` | `{ ok, summary }` or `{ detail }` | `POST :8001/financial-plan/run` |
| `GET` | `/api/rsu-market-data` | — | RSU payload JSON | `GET :8001/rsu-market-data` |
| `POST` | `/api/rsu-refresh` | optional tickers | refresh result | `POST :8001/rsu-refresh` |
| `GET` | `/api/rsu/market-data` | `?ticker=` | legacy | `GET :8001/rsu/market-data` |

### Python chat agent (`:8000`, `agent/main.py`)

| Method | Path | Body | Response |
|--------|------|------|----------|
| `POST` | `/copilotkit` | `RunAgentInput` (AG-UI) | SSE stream |
| `GET` | `/copilotkit/health` | — | `{ status, agent: { name } }` |
| `GET` | `/health` | — | `{ status, agent }` |

### Python financial API (`:8001`, `backend/airtable_main.py`)

| Method | Path | Body | Response |
|--------|------|------|----------|
| `GET` | `/health` | — | `{ status: "ok" }` |
| `GET` | `/clients` | — | `{ clients: [...] }` |
| `GET` | `/clients/{record_id}` | — | `{ record_id, client_data }` |
| `POST` | `/financial-plan/run` | `{ record_id }` | `{ ok: true, summary: {...} }` or HTTP error |
| `GET` | `/rsu-market-data` | — | parquet-derived JSON |
| `POST` | `/rsu-refresh` | `{ tickers?: string[] }` | refresh metadata |
| `GET` | `/rsu/market-data` | query `ticker` | legacy |
| `POST` | `/rsu/market-data/refresh` | query `force`, `ticker` | legacy |

**`summary` shape** (from `summarize_plan_state`): `client_name`, `monthly_surplus`, `risk_appetite`, `liquidity_ratio`, `liquidity_flag`, `flexibility`, `spending_behavior`, `ending_liquid_pool`, `ending_monthly_surplus`, `sorted_goals_preview`, `goal_allocation_preview` (with `funded_from_preview`), `loans_exist`, `final_unused_monthly_surplus`, `retirement_goal_preview`.

---

## 12. The chat agent graph

No hand-written `StateGraph` in `agent/`. `build_graph()` uses `langchain.agents.create_agent()`:

```207:214:agent/main.py
def build_graph():
    return create_agent(
        create_model(),
        tools=[search_internet],
        middleware=[CopilotKitMiddleware()],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=MemorySaver(),
    )
```

Single ReAct loop (model ↔ tools), AG-UI wrapper `LangGraphAGUIAgent(name="dashboard_agent")`. Startup `lifespan` blocks boot if Azure ping fails.

---

## 13. Tools (chat only)

### `searchInternet`

| Aspect | Detail |
|--------|--------|
| Agent | `agent/main.py` `@tool("searchInternet")` |
| Direct Azure | `route.ts` `CopilotRuntime` action |
| Frontend | `useCopilotAction` in `ClientsDashboard.tsx`, `available: "disabled"` |
| Returns | JSON string (agent) or Tavily object (direct) |

No other chat tools.

---

## 14. Frontend ↔ agent shared state

| Readable | File | Content |
|----------|------|---------|
| Current time | `app/page.tsx` | `toLocaleTimeString()` |
| Client list | `ClientsDashboard.tsx` | `{ record_id, name }[]` |
| Selected client | `ClientsDashboard.tsx` | Full Airtable-mapped `client_data` |
| Plan output | `ClientsDashboard.tsx` | `{ record_id, generated, plan_summary? }` from Make plan |

Instructions in `lib/prompt.ts`: prefer plan output when `generated: true`.

---

## 15. How to run locally

**Full experience:** three processes.

```bash
# Terminal 1 — chat agent :8000
cd agent && pip install -r requirements.txt && python main.py

# Terminal 2 — financial API :8001 (Airtable + Make plan)
pip install -r backend/requirements.txt && python backend/airtable_main.py

# Terminal 3 — Next :3000
npm install && npm run dev
```

Set repo-root `.env` from `.env.example` (`AIRTABLE_*`, `AZURE_OPENAI_*` for chat, `AZURE_API_*` for Make plan LLM nodes, `LANGGRAPH_AGENT_URL`, `FASTAPI_BASE_URL`).

**Chat-only (LangGraph):** terminals 1 + 3. **Make plan:** terminal 2 required; uses `AZURE_API_*` inside workflow, not the chat agent process.

---

## 16. How to verify

| Check | Command / action |
|-------|------------------|
| Chat agent | `curl http://localhost:8000/copilotkit/health` |
| Runtime mode | `curl http://localhost:3000/api/copilotkit` |
| Financial API | `curl http://localhost:8001/health` |
| Make plan | Select client → **Make plan** → summary tables populate; Network shows `POST /api/financial-plan/run` 200 |
| Plan in chat | After Make plan, ask sidebar about goal funding — should reference `plan_summary` |
| LangGraph deps on :8001 | Startup log `[financial-plan] langgraph: OK` or WARNING |

---

## 17. Common failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Chat connection refused | Agent not on :8000 | Start `agent/main.py`; check `LANGGRAPH_AGENT_URL` |
| `agent not found` | ID mismatch | Align `dashboard_agent` in `layout.tsx`, `route.ts`, `main.py` |
| Dashboard empty / 502 | :8001 down or bad `AIRTABLE_TOKEN` | Start `airtable_main.py`; fix token/base |
| Make plan 503 | LangGraph not in backend venv | `pip install -r backend/requirements.txt` |
| Make plan 500 | Azure missing for `agentic_nodes` | Set `AZURE_API_*` in `.env` |
| Error says port **8000** for clients | Copy-paste bug in `ClientsDashboard.tsx` | API is **8001** |
| Plan gone after refresh | No persistence | Re-run Make plan |
| Chat cites stale allocations | Old `planResult` readable | Re-run Make plan after data change |

---

## 18. Design decisions and tradeoffs

1. **Separate HTTP workflow vs Copilot tool** — Armstrong pipeline is long-running, synchronous, and needs full `client_data` blob. Exposing it only via `POST /financial-plan/run` avoids AG-UI timeout/streaming complexity and keeps chat tools minimal. **Tradeoff:** chat cannot trigger or monitor plan progress; user must click the button.

2. **Single AG-UI agent for chat** — One `dashboard_agent` matches CopilotKit’s default integration. **Tradeoff:** no first-class “planner agent” in CopilotKit; planning is invisible to the runtime except via readables.

3. **LangGraph for planning with fixed edges** — Explicit `StateGraph` gives auditable order and testable nodes; only two steps use LLM. **Tradeoff:** less flexible than pure agentic planning; LLM cannot skip/reorder nodes.

4. **`summarize_plan_state` instead of persisting full state** — Keeps API payloads small for UI. **Tradeoff:** chat and UI cannot inspect intermediate node outputs; debugging needs server logs (`print` in nodes).

5. **Dual Azure env naming (`AZURE_OPENAI_*` vs `AZURE_API_*`)** — Historical Armstrong vs CopilotKit agent conventions. **Tradeoff:** misconfiguration breaks one path while the other still works.

6. **LangGraph vs direct Azure for chat** — LangGraph mode enables `CopilotKitMiddleware` and future graph extensions; direct mode runs without Python. **Tradeoff:** two code paths, two Tavily SDKs, different error surfaces.

---

## 19. Known limitations and technical debt

- **No `agent/planner/`** — documentation or prompts referring to that path are outdated for this repo.
- **No plan persistence** — results live in React memory only; no Airtable write-back.
- **No auth** on Next or FastAPI routes; CORS `allow_origins=["*"]` on :8001.
- **Chat agent has no financial math tools** — can hallucinate numbers if plan not generated.
- **LLM nodes** (`risk_appetite_assessment`, `goal_prioritization`) can vary run-to-run despite `temperature=0`.
- **Emergency fund node** implemented but **removed from graph** (commented).
- **`education_fees_calculation` returns entire `state`** (in-place mutation) — unusual LangGraph pattern.
- **`plan_goals` conditional maps `'END': END`** but router never returns `'END'`.
- **`check_for_kid` / ages** — year-diff only, not month-accurate.
- **`monthly_surplus` in `calculate_age`** omits EMI deductions (differs from dashboard display in `ClientsDashboard` which may show different surplus).
- **Hardcoded defaults** — retirement life expectancy 85, inflation 6%, real return 4%, EPF 8.5% in mapper, fee fallbacks ₹10L/₹12L.
- **`AIRTABLE_BASE_ID` default** in `airtable_main.py` if env unset (`appE5VYaHMHmorADN`).
- **`ClientsDashboard` error text** references port 8000 instead of 8001.
- **`Financial_Planning/Main/main.py`** — standalone PPT path; extra LLM calls not used by dashboard.
- **`clarify_with_user` tool** uses blocking `input()` — unusable in server context if ever called.
- **Heavy `print` debugging** in workflow nodes — no structured logging.
- **Unused files** — `Dashboard.tsx`, `lib/user-info.ts`, unused npm deps.
- **`SearchResults`** — status only, no Tavily snippets.
- **README `?openCopilot=true`** — no handler in code.

---

## 20. Scalability and production readiness

| Area | Current state | Production would need |
|------|---------------|----------------------|
| Plan storage | Ephemeral | DB/object store per `record_id` + version; optional Airtable write-back |
| Execution | Sync HTTP in API worker | Job queue (Celery/RQ), progress polling, timeout handling |
| Chat state | `MemorySaver` in one process | Durable checkpointer (Postgres), horizontal agent replicas |
| Multi-tenant | Single Airtable base | Per-tenant credentials, authZ on `record_id` |
| Observability | stdout prints | OpenTelemetry, structured logs, node timing metrics |
| LLM cost | Full risk + prioritization per run | Cache by client hash, or deterministic fallback |
| Deploy | Dev three-process | Container orchestration, health checks, secrets manager |
| RSU data | Local parquet | Scheduled refresh, object storage, failure alerts |

---

## 21. Security considerations

| Topic | Current state |
|-------|----------------|
| Secrets | `.env` at repo root (gitignored); loaded by Python and Next |
| API auth | None on Next proxies or FastAPI |
| Airtable token | Server-side only; proxied through Next to FastAPI |
| User input | Chat unauthenticated; `record_id` only validation on plan run |
| Rate limiting | None |
| CORS | `*` on financial API |
| LLM data | Client financial payloads sent to Azure on every Make plan (LLM nodes) and every chat turn |

Treat deployment as **trusted-network demo**, not internet-facing production.

---

## 22. Likely investor questions (pre-answered)

**How do you stop the LLM from inventing financial numbers?**  
Core allocations use deterministic code in `allocations_nodes.py` and `utility_functions.py`. Only risk label and goal ordering use the LLM; numeric outputs for funding come from greedy allocation math. The chat bot can still invent numbers if asked without a generated plan — mitigated only by instructions in `lib/prompt.ts` and the plan readable.

**What happens if a node fails mid-pipeline?**  
`workflow.invoke()` raises; FastAPI returns HTTP 500 with `Financial plan failed: ...`; partial state is not saved. User sees error in `FinancialPlanPanel`; no automatic retry or resume.

**How is this different from a hardcoded calculator?**  
It is largely a **fixed DAG of calculators** with two LLM classification/sorting steps and a prepayment loop. Not a free-form agent choosing formulas.

**Why is the financial math trustworthy?**  
Trust is limited to implemented formulas (documented in node docstrings) and input quality from Airtable mapping. No formal audit, property tests in CI, or separation of actuarial review. LLM steps introduce non-determinism in ordering/labels, not in FV recurrence inside `plan_goals` once goals are sorted.

**How does this scale past N clients?**  
Each Make plan is O(1) sequential invoke per request; no batching. Bottlenecks: synchronous LLM calls (2×), large `plan_goals` / `plan_prepayments` Python work, single-process FastAPI. N parallel users require multiple workers and externalized job queue + plan store.

**What's the vendor lock-in with Azure/CopilotKit?**  
Chat: CopilotKit + AG-UI protocol + LangGraph `create_agent` on Azure OpenAI. Planning: LangGraph `StateGraph` + `langchain-openai` Azure. Porting requires replacing AG-UI bridge, CopilotKit runtime, and Azure SDK calls — workflow math is mostly plain Python.

**Can the AI run a plan from chat?**  
No. Verified: `agent/main.py` exposes only `searchInternet`; planning is HTTP-only from the button.

**Is this multi-agent?**  
No coordinated multi-agent system. One chat ReAct agent plus an inner ReAct helper used inside two workflow nodes, plus a separate batch workflow.

---

## 23. What is not obvious from the code

- **Two runtimes, three ports:** 3000 Next, 8000 chat, 8001 data + planning.
- **Make plan uses `AZURE_API_*`**, chat agent uses `AZURE_OPENAI_*` (with aliases) — configure both for full functionality.
- **`useCopilotAction` + `available: "disabled"`** — UI only; server executes tools.
- **`create_agent` hides chat graph topology** — no `add_node` in `agent/`.
- **Active page is `ClientsDashboard`**, not `Dashboard.tsx`.
- **Education fees in workflow** come from pickle/defaults, not the live Tavily scrapper in `education_fees_scrapper.py`.
- **Full workflow state is discarded** — only `summary` crosses the API boundary.

---

## 24. Things to clean up later

- Fix `ClientsDashboard` port 8000 → 8001 error message.
- Remove dead `'END'` branch in `workflow.py` conditional or implement it.
- Wire or delete emergency-fund node; align surplus definition with dashboard.
- Persist plan results; optional Airtable sync.
- Unify Azure env var names across Python stacks.
- Remove hardcoded `AIRTABLE_BASE_ID` default.
- Add `run_financial_plan` chat tool **only if** product needs it — would require async job design.
- Delete or isolate unused demo components and npm deps.
- Replace node `print` with structured logging for operations.
