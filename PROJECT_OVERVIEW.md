# Project Overview

## 1. What this project does

Users see a **financial planning dashboard** with a client list, per-client portfolio/net-worth views (data from Airtable via a Python API), and a **Copilot sidebar** on the right. They can select clients, browse tabs (overview, kids, liabilities/goals), and ask the assistant questions in natural language about the loaded data or general topics. The AI runs on **Azure OpenAI** (through a LangGraph Python agent by default), receives **dashboard context** from the browser via CopilotKit readables, and can call **`searchInternet`** (Tavily) when the answer needs information outside the dashboard.

## 2. Tech stack

### Frontend

- **Next.js** `^15.5.18` (lockfile resolves to `15.5.18`)
- **React** `^19.0.0` / **react-dom** `^19.0.0` (lockfile: `19.2.0` range)
- **TypeScript** `^5`
- **Tailwind CSS** `^4` (`@tailwindcss/postcss` `^4`)
- **CopilotKit** — `@copilotkit/react-core`, `@copilotkit/react-ui`, `@copilotkit/runtime` each `^1.57.1` (lockfile: `1.57.1`)
- **Vercel AI SDK** — `ai` `^6.0.104`, `@ai-sdk/openai` `^3.0.36`
- **Charts** — `recharts` `^2.15.1`
- **UI** — Radix primitives, `lucide-react`, shadcn-style `components/ui/*`
- **Search (direct-Azure path only)** — `@tavily/core` `^0.3.1`

### Backend agent (LangGraph + AG-UI)

- **Python** (no version pin in repo; use 3.10+ recommended for LangChain 1.x)
- **FastAPI** `>=0.115.0`, **uvicorn** `>=0.32.0`
- **copilotkit** `>=0.1.89`, **ag-ui-langgraph** `>=0.0.35`
- **langgraph** `>=0.4.0`, **langchain** `>=1.0.0`, **langchain-openai** `>=0.3.0`
- **tavily-python** `>=0.5.0`, **python-dotenv** `>=1.0.0`

### Financial data API (Airtable)

- **FastAPI** `>=0.115.0`, **uvicorn** `>=0.32.0`, **requests** `>=2.32.0`, **python-dotenv** `>=1.0.0` (`backend/requirements.txt`)

### LLM / search providers

- **Azure OpenAI** — chat completions (agent: `AZURE_OPENAI_*`; Next.js direct mode: `AZURE_API_*`)
- **OpenAI** — fallback in Next.js direct mode if Azure vars unset (`OPENAI_API_KEY`)
- **Tavily** — web search for `searchInternet` (`TAVILY_API_KEY`)
- **Airtable** — client records (`AIRTABLE_*` via `backend/airtable_main.py`)

**Note:** `package.json` also lists `@tremor/react`, `@hookform/resolvers`, `react-hook-form`, `react-day-picker`, and `zod`, but **no app source file imports them** (likely leftover from the original CopilotKit demo).

## 3. Architecture diagram

```
┌─────────────┐
│    User     │
└──────┬──────┘
       │ types in sidebar
       ▼
┌──────────────────────────────────────────────────────────────┐
│  Browser (React 19)                                          │
│  CopilotSidebar  ←→  CopilotKit provider (app/layout.tsx)    │
│       │                                                      │
│       │  CopilotKit client protocol (HTTP POST + streaming)  │
└───────┼──────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────┐
│  Next.js  /api/copilotkit  (app/api/copilotkit/route.ts)   │
│       │                                                      │
│       ├──[LANGGRAPH_AGENT_URL set]──► LangGraphHttpAgent     │
│       │         HTTP POST  ─────────────────────────────┐    │
│       │                                                 │    │
│       └──[LANGGRAPH_AGENT_URL unset]──► OpenAIAdapter   │    │
│                 Azure/OpenAI Chat Completions (HTTP)    │    │
│                 + Tavily in route handler (direct mode)   │    │
└─────────────────────────────────────────────────────────┼────┘
                                                          │
        ┌─────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────┐
│  Python agent  :8000  POST /copilotkit  (agent/main.py)      │
│       AG-UI SSE (EventEncoder → StreamingResponse)           │
│       LangGraphAGUIAgent.run(RunAgentInput)                  │
│       └── create_agent() ReAct graph + CopilotKitMiddleware  │
│                 ├── Azure OpenAI (langchain-openai)  HTTP    │
│                 └── searchInternet → Tavily API        HTTP    │
└──────────────────────────────────────────────────────────────┘

Parallel data path (not part of chat, but feeds useCopilotReadable):

  ClientsDashboard ──HTTP──► /api/airtable/clients[*] ──HTTP──► :8001 FastAPI ──HTTP──► Airtable API
```

**Protocols by boundary**

| Boundary | Protocol |
|----------|----------|
| User ↔ Browser UI | DOM / React |
| `CopilotSidebar` ↔ `CopilotKit` (`runtimeUrl`) | CopilotKit runtime (HTTP to Next) |
| Next `/api/copilotkit` ↔ Python `:8000/copilotkit` | HTTP POST + **AG-UI SSE** event stream |
| LangGraph agent ↔ Azure OpenAI | HTTPS (Azure OpenAI Chat Completions) |
| `searchInternet` ↔ Tavily | HTTPS (Python `tavily-python` or Node `@tavily/core`) |
| Dashboard ↔ Airtable API | HTTP via Next proxy → FastAPI `:8001` → Airtable REST |

## 4. Request lifecycle, step by step

**Assumption:** `LANGGRAPH_AGENT_URL` is set (recommended path in `.env.example`).

1. **User submits a message** in `CopilotSidebar` (`app/page.tsx` → `HomeContent`).
2. **CopilotKit React client** (`<CopilotKit runtimeUrl="/api/copilotkit" agent="dashboard_agent">` in `app/layout.tsx`) serializes the conversation, frontend **readables** (context), and tool definitions, then **POSTs** to `/api/copilotkit`.
3. **Next.js route** `POST` in `app/api/copilotkit/route.ts` delegates to `copilotRuntimeNextJSAppRouterEndpoint().handleRequest()` with a `CopilotRuntime` built by `createLangGraphRuntime()`.
4. **`LangGraphHttpAgent`** (same file) forwards the run to `LANGGRAPH_AGENT_URL` (default `http://localhost:8000/copilotkit`) over **HTTP**.
5. **Python FastAPI** `langgraph_agent_endpoint()` in `agent/main.py` receives `RunAgentInput`, logs tools/state, clones `agui_agent`, and returns **`StreamingResponse`** encoded with `EventEncoder` (**AG-UI SSE**).
6. **`LangGraphAGUIAgent.run()`** drives the compiled graph from `build_graph()` → `langchain.agents.create_agent(...)` with `CopilotKitMiddleware`, `MemorySaver`, Azure model, and bound tool `searchInternet`.
7. **Azure OpenAI** is invoked by the ReAct loop inside `create_agent`; tool calls are emitted as AG-UI events back through the encoder.
8. **`searchInternet` execution (LangGraph path):** the LLM requests tool `searchInternet` → Python `search_internet()` (`@tool("searchInternet")` in `agent/main.py`) → `TavilyClient.search()` → JSON string returned to the model.
9. **Frontend tool UI (render-only):** `useCopilotAction({ name: "searchInternet", available: "disabled", render: ... })` in `components/ClientsDashboard.tsx` does **not** run search in the browser; `available: "disabled"` means the backend/agent executes it while the UI shows `SearchResults` status (`components/generative-ui/SearchResults.tsx`). `subComponent` is rendered by `CustomAssistantMessage` (`components/AssistantMessage.tsx`).
10. **Assistant text** streams back through CopilotKit to the sidebar; markdown rendered via `Markdown` in `CustomAssistantMessage`.
11. **SSE stream completes**; CopilotKit marks the turn complete.

**Direct Azure path** (no `LANGGRAPH_AGENT_URL`): steps 4–7 go through `createDirectLlmRuntime()` → `OpenAIAdapter` + Azure chat model in `route.ts`; `searchInternet` runs in the `handler` of the `CopilotRuntime` action (lines 84–102) using `@tavily/core`, not Python.

## 5. Modes: LangGraph vs Direct Azure

| | **LangGraph mode** | **Direct Azure mode** |
|---|-------------------|----------------------|
| **Toggle** | `LANGGRAPH_AGENT_URL` set (non-empty after trim) | `LANGGRAPH_AGENT_URL` unset or empty |
| **Checked in** | `app/api/copilotkit/route.ts` (`useLangGraph = Boolean(langGraphAgentUrl)`) and `app/layout.tsx` (sets `agent` prop only when URL set) |
| **Runtime** | `createLangGraphRuntime()` + `LangGraphHttpAgent` → Python | `createDirectLlmRuntime()` + `OpenAIAdapter` → Azure/OpenAI from Next.js |
| **LLM env vars** | `AZURE_OPENAI_*` / `OPENAI_API_VERSION` in **Python** `.env` | `AZURE_API_*` or `OPENAI_API_KEY` in **Next.js** `.env` |
| **Tools** | Python `@tool("searchInternet")` | `CopilotRuntime` `actions` in `route.ts` |
| **User-visible** | Same sidebar UI; needs **Python agent on :8000** running | No Python agent required; chat works with only `npm run dev` if keys are set |
| **Smoke test** | `GET /api/copilotkit` → `{ "mode": "LangGraph", "agents": ["dashboard_agent"], ... }` | `GET /api/copilotkit` → `{ "mode": "direct Azure", ... }` |

If LangGraph mode is enabled but the Python agent is down, chat fails at the proxy step. If `agent` id in `layout.tsx` does not match `LangGraphAGUIAgent.name` in `agent/main.py` (`dashboard_agent`), CopilotKit can report **agent not found**.

## 6. Files inventory

| File path | What it does | What it touches / imports that matters |
|-----------|--------------|----------------------------------------|
| `agent/main.py` | LangGraph agent server: Azure LLM, Tavily tool, AG-UI `/copilotkit` SSE, health routes, startup Azure ping | `create_agent`, `LangGraphAGUIAgent`, `CopilotKitMiddleware`, `EventEncoder`, repo-root `.env` |
| `backend/airtable_main.py` | FastAPI service: lists clients and maps Airtable fields → nested financial JSON | Airtable REST, `AIRTABLE_*` env, runs on `FASTAPI_PORT` (default 8001) |
| `app/layout.tsx` | Root layout; wraps app in `<CopilotKit>` with `runtimeUrl` and optional `agent` id | `@copilotkit/react-core`, `NEXT_PUBLIC_LANGGRAPH_AGENT_ID`, `LANGGRAPH_AGENT_URL` (build-time) |
| `app/page.tsx` | Home page: sidebar + `ClientsDashboard`; exposes clock readable | `CopilotSidebar`, `useCopilotReadable`, `lib/prompt.ts` |
| `app/globals.css` | Tailwind v4 theme + CopilotKit CSS variables | `--copilot-kit-*` colors |
| `app/api/copilotkit/route.ts` | CopilotKit runtime endpoint; LangGraph proxy or direct Azure + Tavily action | `LangGraphHttpAgent`, `CopilotRuntime`, `OpenAIAdapter`, `LANGGRAPH_AGENT_URL` |
| `app/api/airtable/clients/route.ts` | Next proxy: `GET` client list from FastAPI | `FASTAPI_BASE_URL` → `/clients` |
| `app/api/airtable/clients/[id]/route.ts` | Next proxy: `GET` one client’s financial payload | `FASTAPI_BASE_URL` → `/clients/{id}` |
| `components/ClientsDashboard.tsx` | **Active** dashboard: Airtable client UI, charts, Copilot readables + search render action | `/api/airtable/*`, `useCopilotReadable`, `useCopilotAction` |
| `components/Dashboard.tsx` | **Unused** original sales-metrics demo; still has readables + `searchInternet` render | `data/dashboard-data.ts` — **not mounted** in `app/page.tsx` |
| `components/Header.tsx` | Static page header | None |
| `components/Footer.tsx` | Static footer | None |
| `components/AssistantMessage.tsx` | Custom assistant bubble: markdown + loading + `subComponent` (tool UI) | `@copilotkit/react-ui` `Markdown` |
| `components/generative-ui/SearchResults.tsx` | Placeholder UI for `searchInternet` tool status | Used by `useCopilotAction` render |
| `components/ui/card.tsx` | shadcn Card primitives | `lib/utils.ts` `cn()` |
| `components/ui/area-chart.tsx` | Recharts area chart wrapper | `recharts` — used by unused `Dashboard.tsx` |
| `components/ui/bar-chart.tsx` | Recharts bar chart wrapper | `recharts` |
| `components/ui/pie-chart.tsx` | Recharts donut chart wrapper | `recharts` |
| `data/dashboard-data.ts` | Static sample sales/product/regional data + metric helpers | Only imported by `Dashboard.tsx` |
| `lib/prompt.ts` | Copilot sidebar `instructions` string | Imported by `app/page.tsx` |
| `lib/utils.ts` | `cn()` classname helper | `clsx`, `tailwind-merge` |
| `lib/user-info.ts` | Mock user helpers | **Not imported anywhere** (dead code) |
| `next.config.ts` | `allowedDevOrigins`, `outputFileTracingRoot` for standalone deploy | Next config only |

**Hooks not used in this repo:** `useFrontendTool`, `useRenderToolCall`, `useAgent`, `CopilotChat`, `CopilotKitProvider` (the provider is named **`CopilotKit`**).

## 7. Environment variables

| Variable | Required? | What it's for | Example format |
|----------|-----------|---------------|----------------|
| `AZURE_OPENAI_ENDPOINT` | LangGraph path | Azure resource URL for **Python agent** | `https://your-resource.openai.azure.com` |
| `AZURE_OPENAI_API_KEY` | LangGraph path | Azure API key for agent | `abc123...` |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | LangGraph path | Deployment name for agent | `gpt-4o` |
| `OPENAI_API_VERSION` | No | Azure API version for agent (alias: `AZURE_API_VERSION`) | `2024-08-01-preview` |
| `AZURE_API_KEY` | Direct-Azure path | Azure key for **Next.js** `route.ts` | same as above |
| `AZURE_API_BASE` | Direct-Azure path | Azure base URL for Next.js | `https://your-resource.openai.azure.com` |
| `AZURE_DEPLOYMENT_NAME` | Direct-Azure path | Deployment for Next.js adapter | `gpt-4o` |
| `AZURE_API_VERSION` | No | API version for Next.js direct mode | `2024-08-01-preview` |
| `OPENAI_API_KEY` | If no Azure (direct mode) | OpenAI when Azure vars missing in `route.ts` | `sk-...` |
| `TAVILY_API_KEY` | For web search | Tavily for `searchInternet` (both paths) | `tvly-...` |
| `LANGGRAPH_AGENT_URL` | Recommended | Enables LangGraph proxy; URL of Python AG-UI endpoint | `http://localhost:8000/copilotkit` |
| `LANGGRAPH_AGENT_PORT` | No | Port for `python main.py` (default 8000) | `8000` |
| `NEXT_PUBLIC_LANGGRAPH_AGENT_ID` | No | Must match `LangGraphAGUIAgent.name` | `dashboard_agent` |
| `FASTAPI_BASE_URL` | For dashboard data | Next.js → financial API base | `http://localhost:8001` |
| `FASTAPI_PORT` | No | Port for `backend/airtable_main.py` | `8001` |
| `AIRTABLE_BASE_ID` | For real client data | Airtable base | `appXXXXXXXX` |
| `AIRTABLE_TABLE` | No | Table name (default `Table 1`) | `Table 1` |
| `AIRTABLE_TOKEN` | For real client data | Airtable personal access token | `pat...` |

`NODE_ENV=production` is required for `next build` (standard Next.js).

## 8. The agent: graph structure

There is **no hand-written LangGraph `StateGraph` with named nodes** in this repo. The graph is produced by **`langchain.agents.create_agent()`** in `build_graph()` (`agent/main.py`):

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

**Plain English:** this is a **single ReAct-style agent loop** (model ↔ tools) compiled to LangGraph internally, wrapped for AG-UI by `LangGraphAGUIAgent`. **Entry** is whatever `create_agent` defines (typically a model node that can branch to a tool node and back). **Edges** are implicit in that prebuilt graph, not declared in this codebase.

**Tools bound to the LLM:** one — `searchInternet` (`search_internet` function).

**State:** conversation messages plus CopilotKit-injected context from `CopilotKitMiddleware` (frontend readables, frontend tool metadata, etc.) arrive in `RunAgentInput` (`messages`, `tools`, `state` — logged in `_log_run_agent_input`). **Checkpointing:** `MemorySaver()` enables thread persistence within the process (lost on restart).

**Startup:** `lifespan` runs `run_startup_self_test()` — Azure config log + `ainvoke("ping")` before serving traffic.

## 9. Tools

### `searchInternet`

| Aspect | Location |
|--------|----------|
| **Defined (agent)** | `agent/main.py` — `@tool("searchInternet")` → `search_internet(query: str)` |
| **Defined (direct Azure)** | `app/api/copilotkit/route.ts` — `CopilotRuntime` action `name: "searchInternet"` with async `handler` |
| **Registered on frontend** | `components/ClientsDashboard.tsx` — `useCopilotAction({ name: "searchInternet", available: "disabled", render: ... })` |
| **Also registered (unused page)** | `components/Dashboard.tsx` — same pattern (component not mounted) |
| **Name string** | **`searchInternet`** — must match on agent `@tool`, runtime action, and `useCopilotAction` |
| **Behavior** | Tavily search, `max_results: 5` |
| **Returns** | Agent: `json.dumps(...)` of Tavily response, or `{"error": "TAVILY_API_KEY is not configured"}`; Direct mode: Tavily SDK result object from `@tavily/core` |
| **UI** | `SearchResults` shows query + status only (does not list result URLs/snippets) |

No other agent tools are defined in the codebase.

## 10. Frontend ↔ agent shared state

CopilotKit **readables** (`useCopilotReadable`) are sent to the runtime and, in LangGraph mode, through `CopilotKitMiddleware` into the agent run.

| Readable | File | Data exposed | Why the agent needs it |
|----------|------|--------------|------------------------|
| Current time | `app/page.tsx` | `new Date().toLocaleTimeString()` | Time context for answers (e.g. “as of now”) |
| Client list | `components/ClientsDashboard.tsx` | `clients` — `{ record_id, name }[]` from Airtable | Know which clients exist without calling APIs |
| Selected client | `components/ClientsDashboard.tsx` | Full `ClientDetail` object or `"No client selected"` | Answer questions about salary, investments, goals, liabilities for the open client |

**Not exposed (important):** `components/Dashboard.tsx` readables (sample sales metrics) are **never mounted**, so the live app does **not** send sales/chart demo data to the agent unless you switch the page back to `Dashboard`.

## 11. How to run locally

Three processes are required for the **full** experience (chat + Airtable dashboard). Minimum for chat-only in LangGraph mode: agent + Next.js.

### Terminal 1 — LangGraph agent (port 8000)

```bash
cd agent
pip install -r requirements.txt
python main.py
```

**Expected output (success):** log lines including Azure config (masked key), `Azure OpenAI startup ping succeeded`, `Bound tools: ['searchInternet']`, `Starting agent server on :8000`, Uvicorn listening on `0.0.0.0:8000`.

**Health check:**

```bash
curl http://localhost:8000/copilotkit/health
```

**Expected:** `{"status":"ok","agent":{"name":"dashboard_agent"}}`

### Terminal 2 — Airtable / financial API (port 8001)

```bash
pip install -r backend/requirements.txt
python backend/airtable_main.py
```

**Expected:** `Financial Planning API listening on http://0.0.0.0:8001`

```bash
curl http://localhost:8001/health
```

**Expected:** `{"status":"ok"}`

Set `AIRTABLE_TOKEN`, `AIRTABLE_BASE_ID`, and optionally `AIRTABLE_TABLE` in repo-root `.env`.

### Terminal 3 — Next.js (port 3000)

From repo root (after `cp .env.example .env` and filling keys):

```bash
npm install
npm run dev
```

**Expected:** Next.js ready on `http://localhost:3000`; server log `[copilotkit] mode=LangGraph` if `LANGGRAPH_AGENT_URL` is set.

```bash
curl http://localhost:3000/api/copilotkit
```

**Expected (LangGraph):** JSON like `{"mode":"LangGraph","agents":["dashboard_agent"],"langGraphAgentUrl":"http://localhost:8000/copilotkit"}`

Open `http://localhost:3000`, select a client, use the sidebar.

## 12. How to verify it's actually working

| Check | How |
|-------|-----|
| **Agent up** | `curl http://localhost:8000/health` or `/copilotkit/health` |
| **Runtime mode** | `curl http://localhost:3000/api/copilotkit` — confirms LangGraph vs direct |
| **Tool call in Python** | In Terminal 1, after asking “search the web for …”, look for Tavily logs / `searchInternet` in `RunAgentInput: ... tools=...` and no exception stack traces |
| **AG-UI stream** | Browser DevTools → **Network** → POST `/api/copilotkit` → inspect streaming response (SSE/event stream content type from encoder) |
| **Frontend tool UI** | Sidebar shows **Search Results** card with “Searching…” then “Complete” (`SearchResults.tsx`) |
| **Direct hit to agent** | `curl -N -X POST http://localhost:8000/copilotkit -H "Content-Type: application/json" -H "Accept: text/event-stream" -d '{"threadId":"test","runId":"1","messages":[],"tools":[],"state":{}}'` — should stream AG-UI events (minimal body; real runs need valid `RunAgentInput` from CopilotKit) |
| **Dashboard data** | Client list populates; if empty/error, check Terminal 2 and `/api/airtable/clients` |

## 13. Common failure modes

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `TypeError: terminated` (streams / fetch) | Client disconnected, proxy timeout, or aborted SSE during agent/Next streaming | Retry; ensure agent stays up; check reverse-proxy timeouts in production; watch both Next and Python logs for prior exception |
| `EADDRINUSE` / port **8000** in use | Another process on agent port | Stop other service or set `LANGGRAPH_AGENT_PORT` and update `LANGGRAPH_AGENT_URL` |
| **agent not found** / wrong agent | `agent` prop ≠ `LangGraphAGUIAgent.name` | Align `dashboard_agent` in `app/layout.tsx`, `LANGGRAPH_AGENT_ID` in `route.ts`, `agent/main.py`; set `NEXT_PUBLIC_LANGGRAPH_AGENT_ID` if overriding |
| Azure auth / 401 / deployment errors (Python) | Wrong `AZURE_OPENAI_*` for agent | Fix repo-root `.env`; agent fails fast on startup ping if misconfigured |
| Azure **Resource not found** (Next direct mode) | Wrong `AZURE_API_BASE` / deployment name | Match deployment; route uses **Chat Completions**, not Responses API |
| Tavily errors / empty search | Missing `TAVILY_API_KEY` | Set in `.env`; agent returns JSON error string if missing |
| Chat works, dashboard empty | Airtable API not running or bad token | Start `backend/airtable_main.py`; verify `FASTAPI_BASE_URL` |
| Error UI says “port **8000**” for clients | **Misleading message** in `ClientsDashboard.tsx` — data API is **8001** | Start `airtable_main.py` on 8001; ignore the 8000 hint |
| `@copilotkit/*` version mismatch | Mixed package versions | Keep `react-core`, `react-ui`, `runtime` on same version (`^1.57.1`); use `npm ci` with committed lockfile |
| `LANGGRAPH_AGENT_URL` set but connection refused | Agent not started | Run `python agent/main.py` |
| LangGraph mode but used only `AZURE_API_*` | Keys read by wrong stack | Set `AZURE_OPENAI_*` for Python; `AZURE_API_*` for direct Next mode |

## 14. What is NOT obvious from the code

- **Two Azure env naming schemes:** Python agent uses `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY`; Next.js direct mode uses `AZURE_API_BASE` / `AZURE_API_KEY`. `.env.example` documents both; easy to configure one path and break the other.
- **Active dashboard ≠ demo dashboard:** `app/page.tsx` renders `ClientsDashboard`, not `Dashboard.tsx`. Sales sample data and its `useCopilotReadable` are dead for the live app.
- **`useCopilotAction` + `available: "disabled"`:** search runs on the server (agent or Next action), not in the browser; the hook is only for **generative UI rendering**.
- **Agent id `dashboard_agent`:** must match in three places (see section 5).
- **`create_agent` hides the graph:** you will not find `add_node` / `add_edge` in-repo; debugging graph flow means LangChain/LangGraph internals.
- **Startup self-test blocks boot:** bad Azure credentials prevent the agent from serving at all (`SystemExit` after failed ping).
- **`.npmrc` `legacy-peer-deps=true`:** quiets peer conflicts (e.g. React 19 vs older packages); required for reproducible installs per README.
- **ClientsDashboard error text references port 8000** but Airtable FastAPI defaults to **8001** — copy-paste bug.
- **README `?openCopilot=true`:** documented in README but **no code** reads that query param.
- **`lib/user-info.ts`:** sample users, never wired.
- **`SearchResults`:** does not display Tavily hits—only status spinner/text.
- **`backend/airtable_main.py`:** hardcoded default `AIRTABLE_BASE_ID` if env missing — surprising in a fork.
- **Direct mode vs LangGraph:** different Tavily SDKs (`@tavily/core` vs `tavily-python`) and different return shapes for the same tool name.

## 15. Things to clean up later

- Remove or wire up unused `components/Dashboard.tsx` and `data/dashboard-data.ts`, or document as optional demo.
- Delete or use `lib/user-info.ts`.
- Remove unused npm deps: `@tremor/react`, `@hookform/resolvers`, `react-hook-form`, `react-day-picker`, `zod` (if confirmed unused).
- Fix `ClientsDashboard` error message: port **8001** / “Financial Planning API”, not 8000.
- Implement or remove README `?openCopilot=true`.
- Unify Azure env var names across Python and Next.js.
- Remove hardcoded default `AIRTABLE_BASE_ID` in `backend/airtable_main.py`.
- Enrich `SearchResults` to show Tavily snippets/links, or drop generative UI pretense.
- Align `.env.example` / README with `AZURE_OPENAI_*` as primary for the default LangGraph path.
- Add explicit graph diagram or custom nodes only if you outgrow `create_agent`.
- Deduplicate `useCopilotAction` for `searchInternet` (only register once in the mounted tree).
