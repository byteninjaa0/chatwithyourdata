"use client";

import { useEffect, useState, useRef } from "react";
import { useTheme } from "next-themes";
import { useCopilotAction, useCopilotReadable } from "@copilotkit/react-core";
import { SearchResults } from "./generative-ui/SearchResults";
import { CurrentDateTool } from "./generative-ui/CurrentDateTool";
import { FinancialPlanPanel } from "./FinancialPlanPanel";
import { DashboardSidebar } from "./DashboardSidebar";
import { SpouseDetailsPanel, mergeSpouseData, type SpouseData } from "./SpouseDetailsPanel";
import { RealEstateTable, type RealEstateProperty } from "./RealEstateTable";
import { MarriageGoalsSection, type MarriageGoalRow } from "./MarriageGoalsSection";
import { EducationPlanningSection } from "./EducationPlanningSection";
import { buildEducationPlanningBlocks, type EducationPlanningPreviewRow } from "@/lib/educationPlanningView";
import type { EducationTargetYears } from "@/lib/educationTargetYear";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ClientListItem { record_id: string; name: string }

interface FinancialSummary {
  monthly_salary: number;
  monthly_expenses_excl_emis: number;
  "other_income(rental/interest/other)": number;
  lump_sum_available: number;
  emergency_fund_maintained: number;
  miscellaneous_kids_education_expenses_monthly: number;
  annual_vacation_expenses: number;
}

interface Child {
  child_name: string; child_dob: string; Gender: string;
  investments: { type: string; current_value: number; annual_contribution: number; commencement_date: string }[];
}

interface ClientDetail {
  record_id: string;
  client_data: {
    client_data: {
      name: string; pan: string; organization_name: string;
      date_of_birth: string; retirement_age: number;
      spouse_name: string; spouse_dob: string;
      spouse?: SpouseData;
      if_any_kids: boolean; children: Child[];
    };
    investment_details: {
      financial_summary: FinancialSummary[];
      real_estate_investment: RealEstateProperty[];
      retirement_investments: {
        epf: { current_value: number; employee_employer_contribution_monthly: number; interest_rate: number }[];
        ppf: { current_value: number; annual_contribution: number; interest_rate: number }[];
        nps: { current_value: number; monthly_contribution: number; maturity_year: string }[];
        ulip: { current_value: number }[];
      };
      bonds: { bond_name: string; invested_amount: number; interest_rate: number; tenure_years: number }[];
      mutual_funds: { current_value: number; expected_annual_return: number; sip_amount: number }[];
      direct_equity: { portfolio_value: number }[];
      reits: { current_value: number }[];
      pms_aif: { current_value: number }[];
      esops: { vested_esops_value: number; unvested_esops_value: number }[];
      rsu: { company_name: string; ticker: string; vesting_schedule: { year: string; vesting: number; no_shares: number }[] }[];
      fixed_deposits: { name_of_bank: string; principal_amount: number; interest_rate: number; maturity_date: string }[];
      ulips: { policy_name: string; commencement_date: string; annual_premium: number; premium_payment_term: number; policy_term: number; maturity_value: number; maturity_year: number; linked_goal: string }[];
      lic_policies: { policy_name: string; commencement_date: string; annual_premium: number; premium_payment_term: number; policy_period: number; maturity_value: number; linked_goal: string }[];
    };
    financial_goals: { goal_name: string; capital_required_today: number; target_year: number }[];
    liabilities: { type: string; outstanding_balance: number; emi_amount: number; interest_rate: number }[];
    education_planning: {
      name_of_kid: string;
      dob: string;
      graduation_stream: string;
      graduation_destination: string;
      course_duration_ug?: number | null;
      post_graduation_stream: string;
      post_graduation_destination: string;
      course_duration_pg?: number | null;
    }[];
    life_insurance: { company_name: string; coverage_value: number }[];
  };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function inr(n: number | null | undefined): string {
  if (!n) return "—";
  if (n >= 1_00_00_000) return `₹${(n / 1_00_00_000).toFixed(2)}Cr`;
  if (n >= 1_00_000)    return `₹${(n / 1_00_000).toFixed(2)}L`;
  return `₹${n.toLocaleString("en-IN")}`;
}

function pct(r: number) { return r ? `${(r * 100).toFixed(2)}%` : "—"; }

type RsuTickerPrice = {
  price_usd: number;
  price_inr: number;
  usd_to_inr_rate: number;
  scrape_date: string;
};

type RsuMarketMeta = {
  last_update: string | null;
  scrape_date: string | null;
  usd_to_inr_rate: number | null;
  ticker_count?: number;
  parquet_ok?: boolean;
  parquet_row_count?: number;
  parquet_exists?: boolean;
};

function trancheValueInr(
  priceUsd: number,
  usdToInr: number,
  shares: number,
): number {
  return Math.round(priceUsd * usdToInr * shares * 100) / 100;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function KvGrid({ items }: { items: Record<string, string | number | null | undefined> }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 mb-4">
      {Object.entries(items).map(([k, v]) => (
        <div key={k} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 dark:border-gray-700 dark:bg-gray-800/60">
          <p className="mb-1 text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">{k}</p>
          <p className="break-words text-sm font-semibold text-gray-800 dark:text-gray-100">{v ?? "—"}</p>
        </div>
      ))}
    </div>
  );
}

function DataTable({ rows }: { rows: Record<string, string | number>[] }) {
  if (!rows.length) return <p className="text-xs italic text-gray-400 dark:text-gray-500">No data recorded.</p>;
  const cols = Object.keys(rows[0]);
  return (
    <div className="overflow-x-auto mb-2">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-gray-100 dark:bg-gray-800">
            {cols.map(c => <th key={c} className="whitespace-nowrap border-b-2 border-gray-200 px-3 py-1.5 text-left font-semibold text-gray-500 dark:border-gray-600 dark:text-gray-400">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-gray-100 last:border-0 hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-800/50">
              {cols.map(c => <td key={c} className="whitespace-nowrap px-3 py-1.5 text-gray-700 dark:text-gray-300">{r[c] ?? "—"}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SectionLabel({ icon, text }: { icon: string; text: string }) {
  return (
    <div className="flex items-center gap-2 mt-5 mb-2 first:mt-0">
      <span className="inline-flex h-5 w-5 items-center justify-center rounded bg-gray-900 text-[10px] text-white dark:bg-gray-100 dark:text-gray-900">{icon}</span>
      <span className="text-[11px] font-bold uppercase tracking-widest text-gray-600 dark:text-gray-400">{text}</span>
    </div>
  );
}

function StatBox({ label, value, color = "text-gray-900 dark:text-gray-100" }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-lg border border-blue-100 bg-white px-3 py-2.5 dark:border-blue-900/50 dark:bg-gray-900">
      <p className="mb-1 text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">{label}</p>
      <p className={`text-sm font-bold ${color}`}>{value}</p>
    </div>
  );
}

// ── Donut chart (canvas-based, no extra lib) ──────────────────────────────────
function DonutChart({ slices }: { slices: { label: string; value: number; color: string }[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { resolvedTheme } = useTheme();
  const total = slices.reduce((s, x) => s + x.value, 0);
  const holeColor = resolvedTheme === "dark" ? "#111827" : "#ffffff";

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !total) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = canvas.width, H = canvas.height;
    const cx = W / 2, cy = H / 2;
    const outerR = Math.min(cx, cy) - 4;
    const innerR = outerR * 0.55;

    ctx.clearRect(0, 0, W, H);
    let angle = -Math.PI / 2;
    slices.forEach(s => {
      const sweep = (s.value / total) * 2 * Math.PI;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, outerR, angle, angle + sweep);
      ctx.closePath();
      ctx.fillStyle = s.color;
      ctx.fill();
      angle += sweep;
    });

    // Donut hole
    ctx.beginPath();
    ctx.arc(cx, cy, innerR, 0, 2 * Math.PI);
    ctx.fillStyle = holeColor;
    ctx.fill();
  }, [slices, total, holeColor]);

  return (
    <div className="flex flex-col items-center">
      <canvas ref={canvasRef} width={200} height={200} />
      <div className="mt-2 flex flex-wrap justify-center gap-x-3 gap-y-1">
        {slices.map(s => (
          <div key={s.label} className="flex items-center gap-1 text-[10px] text-gray-600 dark:text-gray-400">
            <span className="inline-block w-2 h-2 rounded-sm flex-shrink-0" style={{ background: s.color }} />
            {s.label}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── RSU accordion item ────────────────────────────────────────────────────────
function RsuCard({
  rsu,
  quote,
}: {
  rsu: ClientDetail["client_data"]["investment_details"]["rsu"][0];
  quote?: RsuTickerPrice;
}) {
  const [open, setOpen] = useState(false);
  const total = rsu.vesting_schedule.reduce((s, v) => s + (v.no_shares || 0), 0);
  const totalTranche = quote
    ? rsu.vesting_schedule.reduce(
        (s, v) =>
          s +
          trancheValueInr(
            quote.price_usd,
            quote.usd_to_inr_rate,
            v.no_shares || 0,
          ),
        0,
      )
    : null;
  return (
    <div className="mb-2 overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center justify-between bg-blue-50 px-4 py-3 text-left hover:bg-blue-100 dark:bg-blue-950/40 dark:hover:bg-blue-950/60"
      >
        <span className="text-sm font-bold text-blue-900 dark:text-blue-200">
          {rsu.company_name}{" "}
          {rsu.ticker && (
            <span className="text-xs font-normal text-gray-500 dark:text-gray-400">
              ({rsu.ticker})
              {quote && (
                <span className="ml-1 text-gray-600 dark:text-gray-300">
                  · ${quote.price_usd.toFixed(2)} · ₹
                  {quote.price_inr.toLocaleString("en-IN")}/share
                </span>
              )}
            </span>
          )}
        </span>
        <span className="text-right text-xs text-gray-500 dark:text-gray-400">
          {total.toLocaleString("en-IN")} shares · {rsu.vesting_schedule.length} tranches
          {totalTranche != null && (
            <span className="block font-semibold text-green-700 dark:text-green-400">
              Total: {inr(totalTranche)}
            </span>
          )}{" "}
          {open ? "▲" : "▼"}
        </span>
      </button>
      {open && (
        <div className="bg-gray-50 px-4 py-3 dark:bg-gray-900/50">
          {quote && (
            <p className="mb-2 text-[10px] text-gray-500 dark:text-gray-400">
              FX 1 USD = ₹{quote.usd_to_inr_rate} (as of {quote.scrape_date}) · Tranche
              value = price × FX × shares
            </p>
          )}
          <DataTable
            rows={rsu.vesting_schedule.map((v) => {
              const shares = v.no_shares || 0;
              const tranche =
                quote && shares
                  ? trancheValueInr(
                      quote.price_usd,
                      quote.usd_to_inr_rate,
                      shares,
                    )
                  : null;
              return {
                Year: v.year,
                "Vesting %":
                  v.vesting != null
                    ? `${(v.vesting * 100).toFixed(0)}%`
                    : "—",
                Shares: shares ? shares.toLocaleString("en-IN") : "—",
                "Price (USD)": quote ? `$${quote.price_usd.toFixed(2)}` : "—",
                "FX (USD→INR)": quote
                  ? quote.usd_to_inr_rate.toFixed(2)
                  : "—",
                "Tranche value": tranche != null ? inr(tranche) : "—",
              };
            })}
          />
        </div>
      )}
    </div>
  );
}

function RsuSection({
  rsus,
}: {
  rsus: ClientDetail["client_data"]["investment_details"]["rsu"];
}) {
  const [prices, setPrices] = useState<Record<string, RsuTickerPrice>>({});
  const [meta, setMeta] = useState<RsuMarketMeta | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tickers = [
    ...new Set(
      rsus.map((r) => r.ticker?.trim().toUpperCase()).filter(Boolean) as string[],
    ),
  ];

  const applyMarketPayload = (data: {
    tickers?: Record<string, RsuTickerPrice>;
    usd_to_inr_rate?: number | null;
    scrape_date?: string | null;
    last_updated?: string | null;
    parquet_ok?: boolean;
    parquet_row_count?: number;
  }) => {
    const cache = data.tickers ?? {};
    const subset: Record<string, RsuTickerPrice> = {};
    for (const t of tickers) {
      if (cache[t]) subset[t] = cache[t];
    }
    setPrices(subset);
    setMeta({
      usd_to_inr_rate: data.usd_to_inr_rate ?? null,
      scrape_date: data.scrape_date ?? null,
      last_update: data.last_updated ?? null,
      parquet_ok: data.parquet_ok,
      parquet_row_count: data.parquet_row_count,
    });
  };

  const loadPrices = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/rsu-market-data");
      const data = await res.json();
      if (!res.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : data.error || res.statusText,
        );
      }
      applyMarketPayload(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const refreshPrices = async () => {
    if (tickers.length === 0) return;
    setRefreshing(true);
    setError(null);
    try {
      const res = await fetch("/api/rsu-refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tickers }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : data.error || res.statusText,
        );
      }
      applyMarketPayload(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadPrices();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rsus.map((r) => r.ticker).join(",")]);

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <p className="text-[10px] text-gray-500 dark:text-gray-400">
          {meta?.scrape_date
            ? `Market data: ${meta.scrape_date}`
            : "Load prices to compute tranche values"}
          {meta?.usd_to_inr_rate != null && (
            <span> · USD/INR {meta.usd_to_inr_rate}</span>
          )}
          {meta?.parquet_ok && meta.parquet_row_count != null && (
            <span> · {meta.parquet_row_count} tickers in cache</span>
          )}
        </p>
        <button
          type="button"
          onClick={refreshPrices}
          disabled={refreshing || loading || tickers.length === 0}
          className="inline-flex items-center gap-1.5 rounded-lg bg-blue-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-blue-700 dark:hover:bg-blue-600"
        >
          {refreshing ? (
            <>
              <span className="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Updating prices…
            </>
          ) : (
            "Refresh RSU market data"
          )}
        </button>
      </div>
      {error && (
        <p className="mb-2 rounded border border-red-100 bg-red-50 px-2 py-1 text-xs text-red-600 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-400">
          {error}
        </p>
      )}
      {loading && !refreshing && (
        <p className="mb-2 text-xs text-gray-400 dark:text-gray-500">Loading market prices…</p>
      )}
      {rsus.map((r, i) => (
        <RsuCard
          key={i}
          rsu={r}
          quote={r.ticker ? prices[r.ticker.trim().toUpperCase()] : undefined}
        />
      ))}
    </>
  );
}

// ── Main Dashboard ────────────────────────────────────────────────────────────
export function ClientsDashboard() {
  const [clients, setClients]         = useState<ClientListItem[]>([]);
  const [selectedId, setSelectedId]   = useState<string | null>(null);
  const [detail, setDetail]           = useState<ClientDetail | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError]             = useState<string | null>(null);
  const [activeTab, setActiveTab]     = useState<"overview" | "kids" | "spouse" | "liabilities">("overview");
  const [chartMode, setChartMode]     = useState<"detailed" | "liquid">("detailed");
  const [planResult, setPlanResult]   = useState<{
    ok?: boolean;
    summary?: Record<string, unknown>;
  } | null>(null);

  useEffect(() => {
    fetch("/api/airtable/clients")
      .then(r => r.json())
      .then(data => { if (data.error) throw new Error(data.error); setClients(data.clients ?? []); setLoadingList(false); })
      .catch(e => { setError(e.message); setLoadingList(false); });
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    setLoadingDetail(true); setDetail(null); setActiveTab("overview");
    fetch(`/api/airtable/clients/${selectedId}`)
      .then(r => r.json())
      .then(data => { if (data.error) throw new Error(data.error); setDetail(data); setLoadingDetail(false); })
      .catch(e => { setError(e.message); setLoadingDetail(false); });
  }, [selectedId]);

  useCopilotReadable({ description: "List of financial planning clients", value: clients });
  useCopilotReadable({ description: "Selected client full financial data", value: detail ?? "No client selected" });
  useCopilotReadable({
    description:
      "LangGraph financial plan output for the selected client (from Make plan). Includes goal allocations with funding sources, risk appetite, liquidity, spending behavior, prioritized goals, and retirement scheme breakdown. Not available until the user runs Make plan.",
    value: planResult?.summary
      ? {
          record_id: selectedId,
          generated: true,
          plan_summary: planResult.summary,
        }
      : {
          record_id: selectedId,
          generated: false,
          message:
            "No financial plan has been generated for this client yet. Ask the user to click Make plan first, or answer from input data only.",
        },
  });

  useCopilotAction({
    name: "getCurrentDate",
    available: "disabled",
    description:
      "Returns today's date (ISO) and calendar year for age, retirement, and time-to-goal calculations.",
    parameters: [],
    render: ({ status }) => <CurrentDateTool status={status} />,
  });

  useCopilotAction({
    name: "searchInternet",
    available: "disabled",
    description: "Searches the internet for information.",
    parameters: [
      {
        name: "query",
        type: "string",
        description: "The query to search the internet for.",
        required: true,
      },
    ],
    render: ({ args, status }) => (
      <SearchResults query={args.query || "No query provided"} status={status} />
    ),
  });

  // ── Derived data ───────────────────────────────────────────────────────────
  const cd   = detail?.client_data?.client_data;
  const inv  = detail?.client_data?.investment_details;
  const fs   = inv?.financial_summary?.[0];
  const ret  = inv?.retirement_investments;

  const epfVal  = (ret?.epf  ?? []).reduce((s, x) => s + x.current_value, 0);
  const ppfVal  = (ret?.ppf  ?? []).reduce((s, x) => s + x.current_value, 0);
  const npsVal  = (ret?.nps  ?? []).reduce((s, x) => s + x.current_value, 0);
  const ulipVal = (ret?.ulip ?? []).reduce((s, x) => s + (x.current_value ?? 0), 0);
  const mfVal   = (inv?.mutual_funds ?? []).reduce((s, x) => s + x.current_value, 0);
  const eqVal   = (inv?.direct_equity ?? []).reduce((s, x) => s + x.portfolio_value, 0);
  const fdVal   = (inv?.fixed_deposits ?? []).reduce((s, x) => s + x.principal_amount, 0);
  const reVal   = (inv?.real_estate_investment ?? []).reduce(
    (s, x) => s + (x.current_market_value ?? x.current_value ?? 0),
    0,
  );
  const reitVal = (inv?.reits ?? []).reduce((s, x) => s + x.current_value, 0);
  const pmsVal  = (inv?.pms_aif ?? []).reduce((s, x) => s + x.current_value, 0);
  const bondVal = (inv?.bonds ?? []).reduce((s, x) => s + (x.invested_amount ?? 0), 0);
  const esopVested   = (inv?.esops ?? []).reduce((s, x) => s + x.vested_esops_value, 0);
  const esopUnvested = (inv?.esops ?? []).reduce((s, x) => s + x.unvested_esops_value, 0);

  const totalInvestments = epfVal + ppfVal + npsVal + ulipVal + mfVal + eqVal + fdVal + reVal + reitVal + pmsVal + bondVal + esopVested;
  const totalLiabilities = (detail?.client_data?.liabilities ?? []).reduce((s, l) => s + l.outstanding_balance, 0);
  const netWorth = totalInvestments - totalLiabilities;

  const salary     = fs?.monthly_salary ?? 0;
  const otherInc   = fs?.["other_income(rental/interest/other)"] ?? 0;
  const expenses   = fs?.monthly_expenses_excl_emis ?? 0;
  const vacation   = (fs?.annual_vacation_expenses ?? 0) / 12;
  const misc       = fs?.miscellaneous_kids_education_expenses_monthly ?? 0;
  const surplus    = salary + otherInc - expenses - vacation - misc;
  const totalIncome = salary + otherInc;
  const savingsRate = totalIncome > 0 ? (surplus / totalIncome * 100) : 0;

  // ── Chart slices ───────────────────────────────────────────────────────────
  const detailedSlices = [
    { label: "EPF",             value: epfVal,       color: "#4299e1" },
    { label: "PPF",             value: ppfVal,       color: "#63b3ed" },
    { label: "NPS",             value: npsVal,       color: "#90cdf4" },
    { label: "ULIP",            value: ulipVal,      color: "#bee3f8" },
    { label: "Mutual Funds",    value: mfVal,        color: "#48bb78" },
    { label: "Direct Equity",   value: eqVal,        color: "#ed8936" },
    { label: "Fixed Deposits",  value: fdVal,        color: "#9f7aea" },
    { label: "Real Estate",     value: reVal,        color: "#f6ad55" },
    { label: "REITs",           value: reitVal,      color: "#fc8181" },
    { label: "PMS / AIF",       value: pmsVal,       color: "#68d391" },
    { label: "Bonds",           value: bondVal,      color: "#76e4f7" },
    { label: "ESOPs (Vested)",  value: esopVested,   color: "#b794f4" },
    { label: "ESOPs (Unvested)",value: esopUnvested, color: "#d6bcfa" },
  ].filter(s => s.value > 0);

  const liquidSlices = [
    { label: "Liquid (MF + Equity + REITs)", value: mfVal + eqVal + reitVal, color: "#48bb78" },
    { label: "Fixed (RE + Bonds + PMS + FD + ESOPs)", value: reVal + bondVal + pmsVal + fdVal + esopVested, color: "#ed8936" },
    { label: "Retirement (EPF + PPF + NPS + ULIP)", value: epfVal + ppfVal + npsVal + ulipVal, color: "#4299e1" },
    { label: "ESOPs (Unvested)", value: esopUnvested, color: "#d6bcfa" },
  ].filter(s => s.value > 0);

  const chartSlices = chartMode === "detailed" ? detailedSlices : liquidSlices;

  // ── Goals & liabilities shorthand ─────────────────────────────────────────
  const goals      = detail?.client_data?.financial_goals ?? [];
  const liabilities = detail?.client_data?.liabilities ?? [];
  const liabilitiesToShow = liabilities.filter((item) => {
    const type = String(item.type ?? "").toLowerCase();
    const name = String((item as { name?: string }).name ?? "").toLowerCase();
    return !type.includes("marriage") && !name.includes("marriage");
  });
  const eduPlans   = detail?.client_data?.education_planning ?? [];
  const lifeIns    = detail?.client_data?.life_insurance ?? [];
  const kids       = cd?.children ?? [];

  const hasSpouse = !!(cd?.spouse?.spouse_name || cd?.spouse_name || cd?.spouse?.spouse_dob || cd?.spouse_dob);

  const spouseData: SpouseData | null = mergeSpouseData(
    cd?.spouse,
    planResult?.summary?.spouse_preview as SpouseData | null | undefined,
    { spouse_name: cd?.spouse_name, spouse_dob: cd?.spouse_dob },
  );

  const marriageGoals: MarriageGoalRow[] = (() => {
    const preview = (planResult?.summary?.marriage_goals_preview ?? []) as MarriageGoalRow[];
    if (preview.length) return preview;
    return (goals ?? [])
      .filter(g => /marriage/i.test(g.goal_name))
      .map(g => ({
        goal_name: g.goal_name,
        child_name: g.goal_name.replace(/\s+Marriage$/i, "").trim() || g.goal_name,
        target_year: g.target_year,
        current_cost: g.capital_required_today,
        future_cost: null,
        status: "not_funded",
      }));
  })();

  const educationBlocks = buildEducationPlanningBlocks(eduPlans, kids, {
    targetsPreview: (planResult?.summary?.education_targets_preview ?? []) as Array<
      EducationTargetYears & { child_name?: string }
    >,
    planningPreview: (planResult?.summary?.education_planning_preview ?? []) as EducationPlanningPreviewRow[],
  });

  const realEstateProperties: RealEstateProperty[] =
    ((planResult?.summary?.real_estate_preview as RealEstateProperty[] | undefined)?.length
      ? (planResult!.summary!.real_estate_preview as RealEstateProperty[])
      : inv?.real_estate_investment) ?? [];

  const detailTabs = (
    ["overview", "kids", ...(hasSpouse ? (["spouse"] as const) : []), "liabilities"] as const
  );

  const tabLabel = (tab: (typeof detailTabs)[number]) => {
    if (tab === "overview") return "Overview";
    if (tab === "kids") return "Kid's Details";
    if (tab === "spouse") return "Spouse Details";
    return "Liabilities & Goals";
  };

  useEffect(() => {
    if (!hasSpouse && activeTab === "spouse") setActiveTab("overview");
  }, [hasSpouse, activeTab]);

  const TAB = "px-4 py-1.5 text-xs font-semibold border-b-2 -mb-px cursor-pointer transition-colors";
  const ACTIVE_TAB = `${TAB} border-blue-900 bg-gray-50 text-blue-900 dark:border-blue-400 dark:bg-gray-800 dark:text-blue-300`;
  const IDLE_TAB   = `${TAB} border-transparent text-gray-500 hover:text-blue-700 dark:text-gray-400 dark:hover:text-blue-300`;

  return (
    <div className="relative flex w-full gap-4">
      <DashboardSidebar
        clients={clients}
        selectedId={selectedId}
        onSelect={setSelectedId}
        loadingList={loadingList}
        error={error}
      />

      {/* ── Main area ── */}
      <div className="min-w-0 flex-1">
        {!selectedId && (
          <div className="flex h-64 items-center justify-center rounded-xl border-2 border-dashed border-gray-200 text-sm text-gray-400 dark:border-gray-700 dark:text-gray-500">
            Select a client to view their financial summary
          </div>
        )}
        {selectedId && loadingDetail && (
          <div className="flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
          </div>
        )}

        {detail && !loadingDetail && (
          <div className="flex flex-col gap-4">
            <FinancialPlanPanel
              recordId={selectedId}
              disabled={loadingDetail}
              onPlanResult={setPlanResult}
            />

            {/* ── Net Worth + Portfolio row ── */}
            <div className="flex gap-4 items-stretch">

              {/* Portfolio chart */}
              <div className="flex w-64 shrink-0 flex-col items-center rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900">
                <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-gray-500 dark:text-gray-400">Portfolio Allocation</p>
                <div className="mb-3 flex overflow-hidden rounded border border-gray-200 text-[11px] font-semibold dark:border-gray-600">
                  <button onClick={() => setChartMode("detailed")} className={`px-3 py-1 ${chartMode === "detailed" ? "bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900" : "bg-white text-gray-500 dark:bg-gray-900 dark:text-gray-400"}`}>Detailed</button>
                  <button onClick={() => setChartMode("liquid")}   className={`px-3 py-1 ${chartMode === "liquid"   ? "bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900" : "bg-white text-gray-500 dark:bg-gray-900 dark:text-gray-400"}`}>Liquid &amp; Fixed</button>
                </div>
                <DonutChart slices={chartSlices} />
              </div>

              {/* Net Worth snapshot */}
              <div className="flex-1 rounded-xl border border-blue-100 bg-blue-50 p-4 dark:border-blue-900/50 dark:bg-blue-950/30">
                <p className="mb-3 text-[10px] font-bold uppercase tracking-widest text-blue-700 dark:text-blue-300">Net Worth &amp; Financial Summary</p>
                <div className="grid grid-cols-3 gap-2 mb-2">
                  <StatBox label="Total Investments" value={inr(totalInvestments)} />
                  <StatBox label="Total Liabilities"  value={inr(totalLiabilities)} color="text-red-600 dark:text-red-400" />
                  <StatBox label="Net Worth" value={inr(netWorth)} color={netWorth >= 0 ? "text-green-700 dark:text-green-400" : "text-red-600 dark:text-red-400"} />
                </div>
                <div className="grid grid-cols-3 gap-2 mb-2">
                  <StatBox label="Monthly Salary"   value={inr(salary)} />
                  <StatBox label="Other Income"     value={inr(otherInc)} />
                  <StatBox label="Monthly Expenses" value={inr(expenses)} color="text-red-600 dark:text-red-400" />
                </div>
                <div className="grid grid-cols-3 gap-2 mb-2">
                  <StatBox label="Lump Sum Available" value={inr(fs?.lump_sum_available)} />
                  <StatBox label="Emergency Fund"     value={inr(fs?.emergency_fund_maintained)} />
                  <StatBox label="Annual Vacation"    value={inr(fs?.annual_vacation_expenses)} />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <StatBox label="Monthly Surplus" value={inr(surplus)} color={surplus >= 0 ? "text-green-700 dark:text-green-400" : "text-red-600 dark:text-red-400"} />
                  <StatBox label="Savings Rate" value={`${savingsRate.toFixed(1)}%`} color={savingsRate >= 20 ? "text-green-700 dark:text-green-400" : savingsRate >= 10 ? "text-orange-600 dark:text-orange-400" : "text-red-600 dark:text-red-400"} />
                </div>
              </div>
            </div>

            {/* ── Tabs ── */}
            <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900">
              <div className="flex border-b border-gray-200 px-4 pt-3 dark:border-gray-700">
                {detailTabs.map(tab => (
                  <button key={tab} onClick={() => setActiveTab(tab)} className={activeTab === tab ? ACTIVE_TAB : IDLE_TAB}>
                    {tabLabel(tab)}
                  </button>
                ))}
              </div>

              <div className="p-5">

                {/* ── OVERVIEW TAB ── */}
                {activeTab === "overview" && (
                  <>
                    <SectionLabel icon="👤" text="Personal Details" />
                    <KvGrid items={{
                      Name: cd?.name, "Date of Birth": cd?.date_of_birth,
                      Organization: cd?.organization_name, "Retirement Age": cd?.retirement_age,
                    }} />

                    <SectionLabel icon="🏦" text="Retirement Investments" />
                    <DataTable rows={[
                      ...(ret?.epf ?? []).map(x => ({ Type: "EPF", "Current Value": inr(x.current_value), "Contribution": `${inr(x.employee_employer_contribution_monthly)} /mo`, "Rate": pct(x.interest_rate) })),
                      ...(ret?.ppf ?? []).map(x => ({ Type: "PPF", "Current Value": inr(x.current_value), "Contribution": `${inr(x.annual_contribution)} /yr`, "Rate": pct(x.interest_rate) })),
                      ...(ret?.nps ?? []).map(x => ({ Type: "NPS", "Current Value": inr(x.current_value), "Contribution": `${inr(x.monthly_contribution)} /mo`, "Rate": "—" })),
                    ]} />

                    {(inv?.mutual_funds ?? []).length > 0 && <>
                      <SectionLabel icon="📈" text="Mutual Funds" />
                      <DataTable rows={(inv!.mutual_funds).map(m => ({
                        "Current Value": inr(m.current_value),
                        "SIP Amount": inr(m.sip_amount),
                        "Expected Return": m.expected_annual_return ? `${(m.expected_annual_return * 100).toFixed(1)}%` : "—",
                      }))} />
                    </>}

                    {(inv?.direct_equity ?? []).some(e => e.portfolio_value) && <>
                      <SectionLabel icon="📊" text="Direct Equity" />
                      <DataTable rows={inv!.direct_equity.filter(e => e.portfolio_value).map(e => ({ "Portfolio Value": inr(e.portfolio_value) }))} />
                    </>}

                    {realEstateProperties.some(r => (r.current_market_value ?? r.current_value ?? 0) > 0) && (
                      <>
                        <SectionLabel icon="🏠" text="Real Estate" />
                        <RealEstateTable properties={realEstateProperties} />
                      </>
                    )}

                    {reitVal > 0 && <>
                      <SectionLabel icon="🏢" text="REITs" />
                      <DataTable rows={inv!.reits.filter(r => r.current_value).map(r => ({ "Current Value": inr(r.current_value) }))} />
                    </>}

                    {pmsVal > 0 && <>
                      <SectionLabel icon="🔵" text="PMS / AIF" />
                      <DataTable rows={inv!.pms_aif.filter(p => p.current_value).map(p => ({ "Current Value": inr(p.current_value) }))} />
                    </>}

                    {(inv?.fixed_deposits ?? []).length > 0 && <>
                      <SectionLabel icon="🏧" text="Fixed Deposits" />
                      <DataTable rows={inv!.fixed_deposits.map(f => ({
                        Bank: f.name_of_bank, Principal: inr(f.principal_amount),
                        "Interest Rate": pct(f.interest_rate), "Maturity Date": f.maturity_date || "—",
                      }))} />
                    </>}

                    {(inv?.bonds ?? []).length > 0 && <>
                      <SectionLabel icon="📄" text="Bonds" />
                      <DataTable rows={inv!.bonds.map(b => ({
                        Name: b.bond_name || "—", Amount: inr(b.invested_amount),
                        "Interest Rate": pct(b.interest_rate), "Tenure (yrs)": String(b.tenure_years),
                      }))} />
                    </>}

                    {(esopVested || esopUnvested) ? <>
                      <SectionLabel icon="💻" text="ESOPs" />
                      <DataTable rows={inv!.esops.map(e => ({
                        "Vested Value": inr(e.vested_esops_value), "Unvested Value": inr(e.unvested_esops_value),
                      }))} />
                    </> : null}

                    {(inv?.rsu ?? []).length > 0 && <>
                      <SectionLabel icon="⭐" text="RSUs" />
                      <RsuSection rsus={inv!.rsu} />
                    </>}

                    {(inv?.ulips ?? []).length > 0 && <>
                      <SectionLabel icon="🛡" text="ULIPs" />
                      <DataTable rows={inv!.ulips.map(u => ({
                        "Policy Name": u.policy_name, "Annual Premium": inr(u.annual_premium),
                        "PPT (yrs)": String(u.premium_payment_term), "Term (yrs)": String(u.policy_term),
                        "Maturity Value": inr(u.maturity_value), "Linked Goal": u.linked_goal || "—",
                      }))} />
                    </>}

                    {(inv?.lic_policies ?? []).length > 0 && <>
                      <SectionLabel icon="🔒" text="LIC Policies" />
                      <DataTable rows={inv!.lic_policies.map(l => ({
                        "Policy Name": l.policy_name, "Annual Premium": inr(l.annual_premium),
                        "PPT (yrs)": String(l.premium_payment_term), "Period (yrs)": String(l.policy_period),
                        "Maturity Value": inr(l.maturity_value), "Linked Goal": l.linked_goal || "—",
                      }))} />
                    </>}

                    {lifeIns.length > 0 && <>
                      <SectionLabel icon="❤️" text="Life Insurance" />
                      <DataTable rows={lifeIns.map(l => ({ "Company": l.company_name || "—", "Coverage": inr(l.coverage_value) }))} />
                    </>}
                  </>
                )}

                {/* ── KIDS TAB ── */}
                {activeTab === "kids" && (
                  <>
                    <SectionLabel icon="👶" text="Children" />
                    {kids.length === 0 ? <p className="text-xs italic text-gray-400 dark:text-gray-500">No children recorded.</p> : (
                      <KvGrid items={Object.fromEntries(kids.map(k => [`${k.child_name} (${k.Gender})`, `DOB: ${k.child_dob || "—"}`]))} />
                    )}

                    {kids.some(k => k.investments?.some(i => i.type?.toUpperCase().includes("SUKANYA"))) && <>
                      <SectionLabel icon="⭐" text="Sukanya Samriddhi Yojana (SSY)" />
                      <DataTable rows={kids.flatMap(k =>
                        (k.investments ?? [])
                          .filter(i => i.type?.toUpperCase().includes("SUKANYA"))
                          .map(i => ({
                            Child: k.child_name,
                            "Commencement Date": i.commencement_date || "—",
                            "Annual Contribution": inr(i.annual_contribution),
                            "Current Value": inr(i.current_value),
                          }))
                      )} />
                    </>}

                    {eduPlans.length > 0 && <>
                      <SectionLabel icon="🎓" text="Education Planning" />
                      <EducationPlanningSection blocks={educationBlocks} />
                    </>}

                    <MarriageGoalsSection goals={marriageGoals} />
                  </>
                )}

                {/* ── SPOUSE TAB ── */}
                {activeTab === "spouse" && (
                  spouseData ? (
                    <SpouseDetailsPanel spouse={spouseData} />
                  ) : (
                    <p className="py-8 text-center text-xs text-gray-400 dark:text-gray-500">
                      No spouse information available for this client.
                    </p>
                  )
                )}

                {/* ── LIABILITIES TAB ── */}
                {activeTab === "liabilities" && (
                  <>
                    <SectionLabel icon="⚠️" text="Liabilities" />
                    <DataTable rows={liabilitiesToShow.length ? liabilitiesToShow.map(l => ({
                      Type: l.type, "Outstanding": inr(l.outstanding_balance),
                      "EMI / mo": inr(l.emi_amount), "Interest Rate": pct(l.interest_rate),
                    })) : []} />
                    {liabilitiesToShow.length === 0 && <p className="text-xs italic text-gray-400 dark:text-gray-500">No liabilities recorded.</p>}

                    <SectionLabel icon="🎯" text="Financial Goals" />
                    <DataTable rows={goals.length ? goals.map(g => ({
                      Goal: g.goal_name, "Capital Required": inr(g.capital_required_today), "Target Year": String(g.target_year),
                    })) : []} />
                    {goals.length === 0 && <p className="text-xs italic text-gray-400 dark:text-gray-500">No financial goals recorded.</p>}
                  </>
                )}

              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
