# Chat with your data

AI-powered dashboard assistant built with [CopilotKit](https://copilotkit.ai), Next.js, and Tremor. Ask questions about sample sales metrics in natural language, search the web via Tavily, and see answers in a Copilot sidebar.

![Chat with your data](./preview.gif)

This folder is a **standalone app** — copy it to your own repository; it does not depend on the CopilotKit monorepo.

## Prerequisites

- **Node.js 20+**
- **npm**, **pnpm**, or **yarn**
- An **Azure OpenAI** or **OpenAI** API key
- A **[Tavily](https://tavily.com)** API key (for the `searchInternet` backend action)

## Quick start

1. **Copy or clone** this directory into your project.

2. **Install dependencies:**

   ```bash
   npm install
   ```

   ```bash
   # or
   pnpm install
   ```

3. **Configure environment variables:**

   ```bash
   cp .env.example .env
   ```

   Edit `.env` and set at least:

   - **Azure OpenAI** — `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_DEPLOYMENT_NAME`, and optionally `AZURE_API_VERSION`
   - **or OpenAI** — `OPENAI_API_KEY` (used when Azure variables are unset)
   - **Tavily** — `TAVILY_API_KEY`

4. **Run the dev server:**

   ```bash
   npm run dev
   ```

5. Open [http://localhost:3000](http://localhost:3000).

### Optional query parameter

- `?openCopilot=true` — opens the Copilot sidebar on load.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_API_KEY` | Azure path | Azure OpenAI API key |
| `AZURE_API_BASE` | Azure path | Resource URL, e.g. `https://your-resource.openai.azure.com` |
| `AZURE_DEPLOYMENT_NAME` | Azure path | Deployment name, e.g. `gpt-4o` |
| `AZURE_API_VERSION` | No | API version (default `2024-08-01-preview`) |
| `OPENAI_API_KEY` | OpenAI path | Used when Azure vars are not set |
| `TAVILY_API_KEY` | Yes* | Tavily search for `searchInternet` action |

\*Chat works without Tavily, but web search actions will fail.

> **Azure note:** The API route uses the **Chat Completions** API (`provider.chat()`), not OpenAI’s Responses API, because Azure deployments typically do not expose `/responses`.

## Project structure

```
├── app/
│   ├── api/copilotkit/route.ts   # CopilotKit runtime + Azure/OpenAI + Tavily
│   ├── layout.tsx                # CopilotKit provider
│   └── page.tsx                  # Dashboard + CopilotSidebar
├── components/                   # UI, charts, generative search results
├── data/dashboard-data.ts        # Sample metrics (no external DB)
├── lib/prompt.ts                 # Copilot instructions
├── .env.example
└── package.json
```

## Production build

```bash
# Ensure a standard production env (required for `next build`)
export NODE_ENV=production   # Git Bash / macOS / Linux
# PowerShell: $env:NODE_ENV = "production"

npm run build
npm run start
```

This repo includes `package-lock.json` and `.npmrc` (`legacy-peer-deps=true`) so `npm ci` reproduces the same install on CI and other machines.

Deploy to [Vercel](https://vercel.com) or any Node host; set the same environment variables in the project settings.

## How it works

- **`CopilotKit`** in `app/layout.tsx` points to `/api/copilotkit`.
- **`useCopilotReadable`** in `components/Dashboard.tsx` exposes dashboard JSON to the model.
- **`searchInternet`** is a **backend action** in `app/api/copilotkit/route.ts` (Tavily); the UI renders it via `useCopilotAction` in `Dashboard.tsx`.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| **Resource not found** (Azure) | Confirm deployment name and base URL; ensure Chat Completions is enabled for the deployment. |
| **Agent not found** | This demo has no LangGraph agent — do not set an `agent` prop on `<CopilotKit>`. |
| **ECONNREFUSED** | Ensure `npm run dev` is running; check `runtimeUrl` is `/api/copilotkit`. |
| Tavily errors | Set `TAVILY_API_KEY` in `.env`. |

## License

MIT — see [LICENSE](./LICENSE).

Based on the [CopilotKit chat-with-your-data example](https://github.com/CopilotKit/CopilotKit/tree/main/examples/v1/chat-with-your-data).
