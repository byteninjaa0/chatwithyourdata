"use client";

import * as React from "react";
import {
  Activity,
  ArrowRightLeft,
  Heart,
  Landmark,
  Sparkles,
  Target,
} from "lucide-react";
import { cn } from "@/lib/utils";

type SchemeBreakdownRow = {
  type?: string;
  label?: string;
  amount?: number | null;
  fv?: number | null;
};

type FundedFromRow = Record<string, unknown> & {
  breakdown?: SchemeBreakdownRow[];
  total_fv?: number;
};

type GoalAlloc = {
  goal_name?: string;
  corpus_needed?: number;
  corpus_gap?: number;
  target_corpus?: number;
  target_year?: number;
  filter?: { type?: string }[];
  notes?: string[];
  funded_from_preview?: FundedFromRow[];
};

type PlanSummary = {
  client_name?: string;
  monthly_surplus?: number | null;
  risk_appetite?: { risk_appetite?: string; reason?: string } | Record<string, unknown>;
  liquidity_ratio?: number | null;
  liquidity_flag?: string | null;
  flexibility?: string | null;
  spending_behavior?: Record<string, unknown> | null;
  ending_liquid_pool?: number | null;
  ending_monthly_surplus?: number | null;
  sorted_goals_preview?: {
    goal_name?: string;
    priority_score?: number;
    target_year?: number;
    corpus_needed?: number;
  }[];
  goal_allocation_preview?: GoalAlloc[];
  loans_exist?: boolean;
  final_unused_monthly_surplus?: number | null;
  retirement_goal_preview?: unknown;
};

type PlanResponse = { ok?: boolean; summary?: PlanSummary; detail?: string };

const STEPS = [
  "Loading client data",
  "Calculating asset allocation & ratios",
  "Prioritising financial goals",
  "Allocating surplus & lumpsum",
  "Planning loan prepayments",
  "Selecting optimal strategy",
  "Finalising plan summary",
];

function fmtInr(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function displayFundingType(t: string): string {
  const s = String(t || "");
  if (s === "Retirement Schemes") return "Retirement Schemes";
  if (s === "rsu_funds") return "RSU";
  if (s === "SIP" || s.includes("sip")) return "SIP";
  if (s.includes("freed")) return "Freed EMI";
  if (s.includes("lump")) return "Lumpsum";
  if (s.includes("ssy")) return "SSY";
  if (s.includes("retirement") || s === "future_values_retirement_investments")
    return "Retirement";
  return s.replace(/_/g, " ") || "—";
}

function fundingBadgeClass(displayType: string): string {
  const d = displayType.toUpperCase();
  if (d.includes("SIP")) return "bg-sky-100 text-sky-800";
  if (d.includes("FREED")) return "bg-amber-100 text-amber-900";
  if (d.includes("LUMP")) return "bg-emerald-100 text-emerald-800";
  if (d.includes("SSY")) return "bg-violet-100 text-violet-800";
  if (d.includes("RSU")) return "bg-orange-50 text-orange-800";
  if (d === "EPF" || d === "PPF" || d === "NPS" || d === "ULIP")
    return "bg-purple-100 text-purple-900";
  if (d.includes("RETIREMENT")) return "bg-purple-100 text-purple-900";
  return "bg-slate-100 text-slate-800";
}

function RetirementSchemeBreakdown({
  totalFv,
  breakdown,
}: {
  totalFv?: number;
  breakdown: SchemeBreakdownRow[];
}) {
  return (
    <tr className="bg-violet-50/60">
      <td colSpan={6} className="px-3.5 py-3">
        <div className="mb-2.5 flex flex-wrap items-center gap-2">
          <span
            className={cn(
              "inline-block rounded-xl px-2.5 py-0.5 text-[0.75rem] font-bold",
              fundingBadgeClass("Retirement Schemes"),
            )}
          >
            Retirement Schemes
          </span>
          <span className="text-[0.8rem] text-slate-500">Total future value:</span>
          <strong className="text-purple-900">{fmtInr(totalFv)}</strong>
        </div>
        <div className="flex flex-wrap gap-2.5">
          {breakdown.map((s, j) => {
            const label = s.label || s.type || "Scheme";
            const schemeType = s.type || "Retirement Scheme";
            return (
              <div
                key={j}
                className="min-w-[130px] rounded-lg border border-violet-200 bg-white px-3.5 py-2.5"
              >
                <span
                  className={cn(
                    "mb-2 inline-block rounded-lg px-2 py-0.5 text-[0.72rem] font-bold",
                    fundingBadgeClass(schemeType),
                  )}
                >
                  {label}
                </span>
                <div className="flex gap-5 text-[0.8rem]">
                  <div>
                    <div className="mb-0.5 text-[0.68rem] font-medium uppercase tracking-wide text-slate-500">
                      Current value
                    </div>
                    <div className="font-semibold text-slate-800">
                      {fmtInr(s.amount ?? undefined)}
                    </div>
                  </div>
                  <div>
                    <div className="mb-0.5 text-[0.68rem] font-medium uppercase tracking-wide text-slate-500">
                      Future value
                    </div>
                    <div className="font-bold text-purple-900">
                      {fmtInr(s.fv ?? undefined)}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </td>
    </tr>
  );
}

function deriveGoalStatus(g: GoalAlloc): "funded" | "partial_funded" | "not_funded" {
  const filters = g.filter || [];
  const types = filters.map((f) => (f.type || "").toLowerCase());
  if (types.includes("unfunded")) return "not_funded";
  if (types.includes("partial_funded")) return "partial_funded";
  if (types.includes("funded")) return "funded";
  const gap = Number(g.corpus_gap ?? 0);
  if (gap > 0) return "partial_funded";
  return "funded";
}

function ReviewSectionTitle({
  icon: Icon,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-3.5 flex items-center gap-2 border-b-2 border-sky-200 pb-1.5 text-[0.82rem] font-bold uppercase tracking-[0.07em] text-[#2b6cb0]">
      <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded bg-gray-900 text-white">
        <Icon className="h-3 w-3" strokeWidth={2.5} />
      </span>
      {children}
    </div>
  );
}

function KvGrid({
  items,
}: {
  items: { label: string; value: React.ReactNode }[];
}) {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3">
      {items.map(({ label, value }) => (
        <div
          key={label}
          className="rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-2.5"
        >
          <div className="mb-1 text-[0.72rem] font-medium uppercase tracking-wide text-slate-500">
            {label}
          </div>
          <div className="break-words text-[0.95rem] font-semibold text-slate-700">
            {value}
          </div>
        </div>
      ))}
    </div>
  );
}

function FundingTable({ rows }: { rows: FundedFromRow[] }) {
  if (!rows.length) {
    return (
      <span className="text-[0.8rem] text-slate-400">No allocation recorded</span>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse text-[0.83rem]">
        <thead>
          <tr className="border-b-2 border-slate-200 bg-slate-100 text-left text-slate-600">
            <th className="whitespace-nowrap px-2.5 py-1.5 font-semibold">Source</th>
            <th className="whitespace-nowrap px-2.5 py-1.5 font-semibold">Amount</th>
            <th className="whitespace-nowrap px-2.5 py-1.5 font-semibold">From</th>
            <th className="whitespace-nowrap px-2.5 py-1.5 font-semibold">To</th>
            <th className="whitespace-nowrap px-2.5 py-1.5 font-semibold">Rate</th>
            <th className="whitespace-nowrap px-2.5 py-1.5 font-semibold">FV</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((f, i) => {
            const rawType = String(f.type || "");
            if (rawType === "Retirement Schemes") {
              const breakdown = (f.breakdown as SchemeBreakdownRow[]) || [];
              if (breakdown.length > 0) {
                return (
                  <RetirementSchemeBreakdown
                    key={i}
                    totalFv={f.total_fv as number | undefined}
                    breakdown={breakdown}
                  />
                );
              }
              return (
                <tr key={i} className="border-b border-slate-200 bg-violet-50/40">
                  <td className="px-2.5 py-1.5">
                    <span
                      className={cn(
                        "inline-block rounded-xl px-2.5 py-0.5 text-[0.75rem] font-bold",
                        fundingBadgeClass("Retirement Schemes"),
                      )}
                    >
                      Retirement Schemes
                    </span>
                  </td>
                  <td colSpan={4} className="px-2.5 py-1.5 text-slate-500">
                    Existing retirement investments
                  </td>
                  <td className="px-2.5 py-1.5 font-semibold text-purple-900">
                    {fmtInr(f.total_fv as number | undefined)}
                  </td>
                </tr>
              );
            }
            const display = displayFundingType(rawType);
            const badge = fundingBadgeClass(display);
            const monthly = f.monthly as number | undefined;
            const amountUsed = f.amount_used as number | undefined;
            const amount = f.amount as number | undefined;
            const principal = f.principal_used_today as number | undefined;
            const fv =
              (f.fv_contribution as number | undefined) ??
              (f.fv as number | undefined);
            const fromY = f.from_year as number | string | undefined;
            const toY = f.to_year as number | string | undefined;
            const rate = f.rate as string | undefined;
            const source = f.source as string | undefined;

            let amtCell: React.ReactNode = "—";
            if (rawType === "rsu_funds" && amountUsed != null)
              amtCell = fmtInr(amountUsed);
            else if (monthly != null) amtCell = `${fmtInr(monthly)}/mo`;
            else if (amount != null) amtCell = fmtInr(amount);
            else if (principal != null) amtCell = fmtInr(principal);

            return (
              <tr key={i} className="border-b border-slate-200 hover:bg-slate-50">
                <td className="whitespace-nowrap px-2.5 py-1.5 text-slate-800">
                  <span
                    className={cn(
                      "inline-block rounded-xl px-2.5 py-0.5 text-[0.75rem] font-bold",
                      badge,
                    )}
                  >
                    {display}
                  </span>
                  {source ? (
                    <div className="mt-1 text-[0.78rem] text-slate-500">{source}</div>
                  ) : null}
                </td>
                <td className="whitespace-nowrap px-2.5 py-1.5">{amtCell}</td>
                <td className="whitespace-nowrap px-2.5 py-1.5">
                  {fromY != null && fromY !== "" ? String(fromY) : "—"}
                </td>
                <td className="whitespace-nowrap px-2.5 py-1.5">
                  {toY != null && toY !== "" ? String(toY) : "—"}
                </td>
                <td className="whitespace-nowrap px-2.5 py-1.5">
                  {rate != null ? String(rate) : "—"}
                </td>
                <td className="whitespace-nowrap px-2.5 py-1.5">
                  {fv != null ? fmtInr(fv) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PlanGeneratingOverlay({ activeStep }: { activeStep: number }) {
  const pct = Math.min(100, Math.round(((activeStep + 1) / STEPS.length) * 82));

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/80 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="plan-overlay-title"
    >
      <div className="mx-4 w-full max-w-[460px] rounded-2xl bg-white px-10 py-10 text-center shadow-2xl">
        <div
          className="mx-auto mb-5 h-14 w-14 animate-spin rounded-full border-[5px] border-slate-200 border-t-[#1a365d]"
          aria-hidden
        />
        <h2
          id="plan-overlay-title"
          className="mb-1.5 text-lg font-bold text-slate-900"
        >
          Generating Financial Plan
        </h2>
        <p className="mb-6 text-[0.83rem] text-slate-500">
          Running AI workflow… this may take 1–3 minutes.
        </p>
        <div className="mb-5 h-1.5 overflow-hidden rounded-full bg-slate-200">
          <div
            className="h-full rounded-full bg-[#1a365d] transition-[width] duration-1000 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="space-y-1 text-left text-[0.82rem]">
          {STEPS.map((label, i) => (
            <div
              key={label}
              className={cn(
                "flex items-center gap-2.5 py-1 transition-colors",
                i < activeStep && "font-medium text-emerald-700",
                i === activeStep && "font-semibold text-slate-900",
                i > activeStep && "text-slate-400",
              )}
            >
              <span
                className={cn(
                  "h-2 w-2 shrink-0 rounded-full",
                  i < activeStep && "bg-emerald-500",
                  i === activeStep && "bg-[#1a365d] shadow-[0_0_0_3px_rgba(26,54,93,0.2)]",
                  i > activeStep && "bg-slate-200",
                )}
              />
              {label}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function FinancialPlanPanel({
  recordId,
  disabled,
  onPlanResult,
}: {
  recordId: string | null;
  disabled?: boolean;
  /** Notifies parent when plan completes — used for CopilotKit context. */
  onPlanResult?: (result: PlanResponse | null) => void;
}) {
  const [loading, setLoading] = React.useState(false);
  const [overlayStep, setOverlayStep] = React.useState(0);
  const [result, setResult] = React.useState<PlanResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [status, setStatus] = React.useState<{
    msg: string;
    type: "info" | "success" | "error";
  } | null>(null);

  React.useEffect(() => {
    setResult(null);
    setError(null);
    setStatus(null);
    onPlanResult?.(null);
  }, [recordId, onPlanResult]);

  React.useEffect(() => {
    if (!loading) {
      setOverlayStep(0);
      return;
    }
    const t0 = window.setTimeout(() => setOverlayStep(1), 5000);
    const t1 = window.setTimeout(() => setOverlayStep(2), 15000);
    const t2 = window.setTimeout(() => setOverlayStep(3), 28000);
    const t3 = window.setTimeout(() => setOverlayStep(4), 45000);
    const t4 = window.setTimeout(() => setOverlayStep(5), 62000);
    const t5 = window.setTimeout(() => setOverlayStep(6), 78000);
    return () => {
      clearTimeout(t0);
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      clearTimeout(t4);
      clearTimeout(t5);
    };
  }, [loading]);

  const runPlan = async () => {
    if (!recordId) return;
    setLoading(true);
    setError(null);
    setResult(null);
    onPlanResult?.(null);
    setStatus({ msg: "Generating financial plan…", type: "info" });
    try {
      const res = await fetch("/api/financial-plan/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record_id: recordId }),
      });
      const data = (await res.json()) as PlanResponse;
      if (!res.ok) {
        const msg =
          typeof data.detail === "string" ? data.detail : "Plan run failed";
        setError(msg);
        setStatus({ msg, type: "error" });
        return;
      }
      setResult(data);
      onPlanResult?.(data);
      setStatus({
        msg: "Plan ready — review below.",
        type: "success",
      });
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg);
      onPlanResult?.(null);
      setStatus({ msg, type: "error" });
    } finally {
      setLoading(false);
    }
  };

  const s = result?.summary;
  const sb = s?.spending_behavior;
  const savingPct =
    sb && typeof sb.saving_ratio === "number"
      ? sb.saving_ratio * 100
      : null;
  const expensePct =
    sb && typeof sb.expense_ratio === "number"
      ? sb.expense_ratio * 100
      : null;
  const redFlag = Boolean(sb?.red_flag);
  const liqFlag = String(s?.liquidity_flag ?? "");
  const flex = String(s?.flexibility ?? "");
  const liqOk = liqFlag.toLowerCase().includes("ok");
  const flexOk =
    flex.toLowerCase().includes("medium") ||
    flex.toLowerCase().includes("high");

  return (
    <>
      {loading ? <PlanGeneratingOverlay activeStep={overlayStep} /> : null}

      <div className="mb-6 overflow-hidden rounded-xl border border-slate-200 bg-[#f0f4f8] shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b-2 border-[#1a365d] bg-white px-5 py-4 shadow-sm">
          <div>
            <p className="text-[0.72rem] font-bold uppercase tracking-widest text-[#1a365d]">
              Financial Plan Generator
            </p>
            <p className="text-xs text-slate-500">
              Strategizing wealth, maximizing opportunities · Armstrong workflow
            </p>
          </div>
          <button
            type="button"
            onClick={runPlan}
            disabled={disabled || loading || !recordId}
            className={cn(
              "inline-flex shrink-0 items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-semibold text-white transition",
              "bg-[#2b6cb0] hover:bg-[#2c5282] disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            {loading ? (
              <>
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                Generating…
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                Make plan
              </>
            )}
          </button>
        </div>

        <div className="p-5 sm:p-6">
          {status ? (
            <div
              className={cn(
                "mb-4 rounded-lg px-4 py-3 text-sm font-medium",
                status.type === "info" && "bg-sky-50 text-sky-800",
                status.type === "success" && "bg-emerald-50 text-emerald-900",
                status.type === "error" && "bg-red-50 text-red-800",
              )}
            >
              {status.msg}
            </div>
          ) : null}

          {error && status?.type !== "error" ? (
            <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800">
              {error}
            </div>
          ) : null}

          {s ? (
            <div className="rounded-xl border border-slate-200/80 bg-white px-6 py-7 shadow-sm">
              <h2 className="mb-5 text-base font-semibold uppercase tracking-wider text-slate-700">
                Plan review
              </h2>

              {/* Financial health */}
              <div className="mb-7">
                <ReviewSectionTitle icon={Heart}>Financial health</ReviewSectionTitle>
                {redFlag ? (
                  <div className="mb-3.5 border-l-4 border-amber-500 bg-amber-50 py-2.5 pl-3.5 pr-3 text-amber-950">
                    <p className="mb-1 text-[0.78rem] font-bold uppercase tracking-wide text-amber-900">
                      Spending ratio alert
                    </p>
                    <p className="text-[0.85rem] leading-relaxed">
                      Spending ratio exceeds recommended threshold. Consider
                      reviewing discretionary expenses.
                    </p>
                  </div>
                ) : null}
                <KvGrid
                  items={[
                    {
                      label: "Savings rate",
                      value: (
                        <span
                          className={cn(
                            savingPct != null &&
                              savingPct >= 20 &&
                              "text-emerald-700",
                            savingPct != null &&
                              savingPct < 20 &&
                              savingPct >= 10 &&
                              "text-orange-700",
                            savingPct != null &&
                              savingPct < 10 &&
                              "text-red-700",
                          )}
                        >
                          {savingPct != null ? `${savingPct.toFixed(1)}%` : "—"}
                        </span>
                      ),
                    },
                    {
                      label: "Expense ratio",
                      value: (
                        <span
                          className={cn(
                            expensePct != null &&
                              expensePct <= 60 &&
                              "text-emerald-700",
                            expensePct != null &&
                              expensePct > 60 &&
                              expensePct <= 70 &&
                              "text-orange-700",
                            expensePct != null &&
                              expensePct > 70 &&
                              "text-red-700",
                          )}
                        >
                          {expensePct != null ? `${expensePct.toFixed(1)}%` : "—"}
                        </span>
                      ),
                    },
                    {
                      label: "Liquidity",
                      value: (
                        <span
                          className={cn(
                            "inline-block rounded px-2 py-0.5 text-[0.8rem] font-semibold",
                            liqOk
                              ? "border border-emerald-300 bg-emerald-50 text-emerald-800"
                              : "border border-orange-300 bg-orange-50 text-orange-800",
                          )}
                        >
                          {liqFlag || "—"}
                        </span>
                      ),
                    },
                    {
                      label: "Flexibility",
                      value: (
                        <span
                          className={cn(
                            "inline-block rounded px-2 py-0.5 text-[0.8rem] font-semibold",
                            flexOk
                              ? "border border-emerald-300 bg-emerald-50 text-emerald-800"
                              : "border border-orange-300 bg-orange-50 text-orange-800",
                          )}
                        >
                          {flex || "—"}
                        </span>
                      ),
                    },
                  ]}
                />
              </div>

              {/* Risk */}
              <div className="mb-7">
                <ReviewSectionTitle icon={Activity}>Risk appetite</ReviewSectionTitle>
                <div className="rounded-lg border border-slate-200 bg-slate-50/80 p-4 text-sm text-slate-800">
                  {(() => {
                    const ra = s.risk_appetite as Record<string, unknown> | undefined;
                    const inner = ra?.risk_appetite as
                      | { risk_appetite?: string; reason?: string }
                      | string
                      | undefined;
                    const label =
                      typeof inner === "string"
                        ? inner
                        : inner && typeof inner === "object"
                          ? inner.risk_appetite
                          : null;
                    const reason =
                      inner && typeof inner === "object" ? inner.reason : undefined;
                    return (
                      <>
                        <p className="font-semibold text-[#1a365d]">
                          {label ?? "—"}
                        </p>
                        {reason ? (
                          <p className="mt-2 text-[0.85rem] leading-relaxed text-slate-600">
                            {reason}
                          </p>
                        ) : null}
                      </>
                    );
                  })()}
                </div>
              </div>

              {/* Surplus & pools */}
              <div className="mb-7">
                <ReviewSectionTitle icon={ArrowRightLeft}>
                  Surplus &amp; asset pools
                </ReviewSectionTitle>
                <KvGrid
                  items={[
                    {
                      label: "Monthly surplus",
                      value: (
                        <span className="text-emerald-800">
                          {fmtInr(s.monthly_surplus ?? undefined)}
                        </span>
                      ),
                    },
                    {
                      label: "Unused monthly surplus",
                      value: fmtInr(s.final_unused_monthly_surplus ?? undefined),
                    },
                    {
                      label: "Ending liquid pool",
                      value: fmtInr(s.ending_liquid_pool ?? undefined),
                    },
                    {
                      label: "Ending monthly surplus (alloc)",
                      value: fmtInr(s.ending_monthly_surplus ?? undefined),
                    },
                  ]}
                />
              </div>

              {/* Goal allocations — cards like reference HTML */}
              {s.goal_allocation_preview && s.goal_allocation_preview.length > 0 ? (
                <div className="mb-7">
                  <ReviewSectionTitle icon={Target}>
                    Goal allocations
                  </ReviewSectionTitle>
                  <div className="space-y-4">
                    {s.goal_allocation_preview.map((g, idx) => {
                      const status = deriveGoalStatus(g);
                      const gap = Number(g.corpus_gap ?? 0);
                      const partial = status === "partial_funded" || gap > 0;
                      return (
                        <div
                          key={`${g.goal_name}-${idx}`}
                          className={cn(
                            "rounded-lg border bg-slate-50 p-3.5 sm:p-4",
                            partial
                              ? "border-amber-300"
                              : "border-slate-200",
                          )}
                        >
                          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                            <strong className="text-[0.95rem] text-slate-900">
                              {g.goal_name}
                            </strong>
                            <span
                              className={cn(
                                "inline-block rounded-xl px-2.5 py-0.5 text-[0.75rem] font-bold uppercase",
                                status === "funded" &&
                                  "bg-emerald-50 text-emerald-800",
                                status === "partial_funded" &&
                                  "bg-amber-50 text-amber-900",
                                status === "not_funded" &&
                                  "bg-red-50 text-red-800",
                              )}
                            >
                              {status.replaceAll("_", " ")}
                            </span>
                          </div>
                          <div className="mb-2.5 text-[0.82rem] text-slate-500">
                            Target year:{" "}
                            <strong className="text-slate-800">
                              {g.target_year ?? "—"}
                            </strong>
                            {" · "}
                            Target corpus:{" "}
                            <strong className="text-slate-800">
                              {fmtInr(g.target_corpus)}
                            </strong>
                            {partial && gap > 0 ? (
                              <>
                                {" · "}
                                Corpus gap:{" "}
                                <strong className="text-orange-800">
                                  {fmtInr(gap)}
                                </strong>
                              </>
                            ) : null}
                          </div>
                          {g.funded_from_preview && g.funded_from_preview.length > 0 ? (
                            <div className="mt-2">
                              <FundingTable rows={g.funded_from_preview} />
                            </div>
                          ) : null}
                          {(status === "partial_funded" ||
                            status === "not_funded") &&
                          (g.notes?.length || gap > 0) ? (
                            <div className="mt-3 border-l-4 border-amber-500 bg-amber-50 py-2.5 pl-3 pr-2 text-amber-950">
                              <p className="mb-1 text-[0.78rem] font-bold uppercase tracking-wide text-amber-900">
                                Action required
                              </p>
                              <div className="text-[0.85rem] leading-relaxed">
                                {g.notes?.length ? (
                                  <ul className="list-inside list-disc space-y-1">
                                    {g.notes.map((n, j) => (
                                      <li key={j}>{n}</li>
                                    ))}
                                  </ul>
                                ) : (
                                  <p>
                                    Corpus gap of {fmtInr(gap)} remains for this
                                    goal.
                                  </p>
                                )}
                              </div>
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : null}

              {/* Prioritized goals table */}
              {s.sorted_goals_preview && s.sorted_goals_preview.length > 0 ? (
                <div className="mb-7">
                  <ReviewSectionTitle icon={Landmark}>
                    Prioritized goals
                  </ReviewSectionTitle>
                  <div className="overflow-x-auto rounded-lg border border-slate-200">
                    <table className="min-w-full border-collapse text-[0.83rem]">
                      <thead>
                        <tr className="border-b-2 border-slate-200 bg-slate-100 text-left text-slate-600">
                          <th className="px-2.5 py-1.5 font-semibold">Goal</th>
                          <th className="px-2.5 py-1.5 font-semibold">Score</th>
                          <th className="px-2.5 py-1.5 font-semibold">Year</th>
                          <th className="px-2.5 py-1.5 font-semibold">Corpus</th>
                        </tr>
                      </thead>
                      <tbody>
                        {s.sorted_goals_preview.map((row, i) => (
                          <tr
                            key={i}
                            className="border-b border-slate-200 hover:bg-slate-50"
                          >
                            <td className="px-2.5 py-1.5 text-slate-800">
                              {row.goal_name}
                            </td>
                            <td className="px-2.5 py-1.5">
                              {row.priority_score ?? "—"}
                            </td>
                            <td className="px-2.5 py-1.5">
                              {row.target_year ?? "—"}
                            </td>
                            <td className="px-2.5 py-1.5">
                              {fmtInr(row.corpus_needed)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}

            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}
