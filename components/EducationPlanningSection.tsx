"use client";

import type { EducationChildBlock, EducationStageView } from "@/lib/educationPlanningView";

const TH =
  "align-middle px-4 py-2 text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400";
const TD = "align-middle px-4 py-2 text-gray-700 dark:text-gray-300";

function fmtInr(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

/** Target Amount = future_cost / ug_future_cost / pg_future_cost (inflated corpus at target year). */
function StageTable({ stage }: { stage: EducationStageView }) {
  return (
    <table className="w-full border-collapse text-xs">
      <thead>
        <tr className="border-b border-gray-100 bg-gray-50 dark:border-gray-700 dark:bg-gray-800">
          <th className={`${TH} text-left`}>Stream</th>
          <th className={`${TH} text-center`}>Course Duration</th>
          <th className={`${TH} text-center`}>Target Year</th>
          <th className={`${TH} text-right`}>Target Amount</th>
        </tr>
      </thead>
      <tbody>
        <tr className="border-b border-gray-100 hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-800/50">
          <td className={`${TD} text-left text-gray-900 dark:text-gray-100`}>
            {stage.stream ?? "—"}
          </td>
          <td className={`${TD} text-center`}>
            {stage.duration != null ? `${stage.duration} yrs` : "—"}
          </td>
          <td className={`${TD} text-center`}>{stage.targetYear ?? "—"}</td>
          <td className={`${TD} text-right font-semibold text-gray-900 dark:text-gray-100`}>
            {fmtInr(stage.futureCost)}
          </td>
        </tr>
      </tbody>
    </table>
  );
}

export function EducationPlanningSection({ blocks }: { blocks: EducationChildBlock[] }) {
  if (!blocks.length) return null;

  return (
    <div className="education-planning-section mt-0">
      {blocks.map((child, idx) => (
        <div
          className={`child-education-block ${idx < blocks.length - 1 ? "mb-8" : ""}`}
          key={child.name}
        >
          <div className="mb-3 text-base font-semibold text-gray-800 dark:text-gray-100">
            🎓 {child.name}
            {child.age != null && (
              <span className="ml-2 text-sm font-normal text-gray-500 dark:text-gray-400">
                (Current age: {child.age})
              </span>
            )}
          </div>

          <div className="ug-section mb-4">
            <div className="mb-2 text-sm font-semibold text-gray-700 dark:text-gray-300">
              Undergraduate ({child.ug.stream ?? "—"})
            </div>
            <StageTable stage={child.ug} />
          </div>

          {child.hasPg && child.pg ? (
            <div className="pg-section">
              <div className="mb-2 text-sm font-semibold text-gray-700 dark:text-gray-300">
                Postgraduate ({child.pg.stream ?? "—"})
              </div>
              <StageTable stage={child.pg} />
            </div>
          ) : (
            <div className="text-xs italic text-gray-400 dark:text-gray-500">
              No postgraduate education planned for {child.name}.
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
