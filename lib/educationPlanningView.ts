/**
 * Builds per-child education blocks for the Kids tab UI (UG + PG sub-tables).
 * Target years: computeEducationTargetYears pre-plan, backend preview post-plan.
 */

import {
  computeEducationTargetYears,
  type EducationTargetYears,
} from "@/lib/educationTargetYear";

export type EducationPlanRow = {
  name_of_kid: string;
  dob?: string;
  graduation_stream?: string | null;
  graduation_destination?: string | null;
  course_duration_ug?: number | null;
  post_graduation_stream?: string | null;
  post_graduation_destination?: string | null;
  course_duration_pg?: number | null;
};

export type EducationStageView = {
  stream: string | null;
  destination: string | null;
  duration: number | null;
  targetYear: number | null;
  currentCost: number | null;
  futureCost: number | null;
  corpusGap: number | null;
  status: "funded" | "partial" | "not_funded" | null;
};

export type EducationChildBlock = {
  name: string;
  age: number | null;
  ug: EducationStageView;
  pg: EducationStageView | null;
  hasPg: boolean;
};

export type EducationPlanningPreviewRow = EducationTargetYears & {
  child_name?: string;
  dob?: string;
  ug_stream?: string | null;
  ug_destination?: string | null;
  ug_current_cost?: number | null;
  ug_future_cost?: number | null;
  ug_corpus_gap?: number | null;
  ug_status?: string | null;
  pg_destination?: string | null;
  pg_current_cost?: number | null;
  pg_future_cost?: number | null;
  pg_corpus_gap?: number | null;
  pg_status?: string | null;
};

/** Matches backend basic_calculations_nodes child_age (year diff only). */
export function childAgeFromDob(dob: string, referenceYear = new Date().getFullYear()): number | null {
  const d = new Date(dob);
  if (Number.isNaN(d.getTime())) return null;
  return referenceYear - d.getFullYear();
}

function normalizeStatus(raw: unknown): EducationStageView["status"] {
  const s = String(raw ?? "").toLowerCase();
  if (s === "funded") return "funded";
  if (s === "partial" || s === "partial_funded") return "partial";
  if (s === "not_funded" || s === "unfunded") return "not_funded";
  return null;
}

function hasPgTarget(targets: EducationTargetYears): boolean {
  if (targets.pg_target_year == null) return false;
  return String(targets.pg_stream ?? "").trim().toUpperCase() !== "NA";
}

function emptyStage(): EducationStageView {
  return {
    stream: null,
    destination: null,
    duration: null,
    targetYear: null,
    currentCost: null,
    futureCost: null,
    corpusGap: null,
    status: null,
  };
}

function stageFromPreview(
  side: "ug" | "pg",
  preview: EducationPlanningPreviewRow,
  planRow: EducationPlanRow,
): EducationStageView {
  const stream =
    (side === "ug" ? preview.ug_stream ?? planRow.graduation_stream : preview.pg_stream) ?? null;
  const destination =
    (side === "ug"
      ? preview.ug_destination ?? planRow.graduation_destination
      : preview.pg_destination ?? planRow.post_graduation_destination) ?? null;

  return {
    stream: stream != null && String(stream).trim() !== "" ? String(stream) : null,
    destination: destination != null && String(destination).trim() !== "" ? String(destination) : null,
    duration: side === "ug" ? preview.ug_duration ?? null : preview.pg_duration ?? null,
    targetYear: side === "ug" ? preview.ug_target_year ?? null : preview.pg_target_year ?? null,
    currentCost:
      side === "ug" ? preview.ug_current_cost ?? null : preview.pg_current_cost ?? null,
    futureCost:
      side === "ug" ? preview.ug_future_cost ?? null : preview.pg_future_cost ?? null,
    corpusGap:
      side === "ug" ? preview.ug_corpus_gap ?? null : preview.pg_corpus_gap ?? null,
    status: normalizeStatus(side === "ug" ? preview.ug_status : preview.pg_status),
  };
}

function stageFromPlanRow(
  side: "ug" | "pg",
  planRow: EducationPlanRow,
  targets: EducationTargetYears,
): EducationStageView {
  return {
    stream:
      side === "ug"
        ? planRow.graduation_stream ?? null
        : (targets.pg_stream != null ? String(targets.pg_stream) : planRow.post_graduation_stream ?? null),
    destination:
      side === "ug"
        ? planRow.graduation_destination ?? null
        : planRow.post_graduation_destination ?? null,
    duration: side === "ug" ? targets.ug_duration : targets.pg_duration,
    targetYear: side === "ug" ? targets.ug_target_year : targets.pg_target_year,
    currentCost: null,
    futureCost: null,
    corpusGap: null,
    status: null,
  };
}

export function buildEducationChildBlock(
  planRow: EducationPlanRow,
  dob: string,
  targets: EducationTargetYears,
  previewRow?: EducationPlanningPreviewRow | null,
): EducationChildBlock {
  const pg = hasPgTarget(targets);
  const ug = previewRow
    ? stageFromPreview("ug", previewRow, planRow)
    : stageFromPlanRow("ug", planRow, targets);

  return {
    name: planRow.name_of_kid,
    age: childAgeFromDob(dob),
    ug,
    pg: pg
      ? previewRow
        ? stageFromPreview("pg", previewRow, planRow)
        : stageFromPlanRow("pg", planRow, targets)
      : null,
    hasPg: pg,
  };
}

export function buildEducationPlanningBlocks(
  eduPlans: EducationPlanRow[],
  kids: { child_name: string; child_dob: string }[],
  options?: {
    targetsPreview?: Array<EducationTargetYears & { child_name?: string }>;
    planningPreview?: EducationPlanningPreviewRow[];
  },
): EducationChildBlock[] {
  const targetsByName = new Map<string, EducationTargetYears>();
  for (const row of options?.targetsPreview ?? []) {
    const name = row.child_name ?? "";
    if (name) targetsByName.set(name, row);
  }

  const planningByName = new Map<string, EducationPlanningPreviewRow>();
  for (const row of options?.planningPreview ?? []) {
    const name = row.child_name ?? "";
    if (name) planningByName.set(name, row);
  }

  return eduPlans.map((planRow) => {
    const dob = planRow.dob || kids.find((k) => k.child_name === planRow.name_of_kid)?.child_dob || "";
    const previewRow = planningByName.get(planRow.name_of_kid);
    const fromPreview = targetsByName.get(planRow.name_of_kid);
    const targets =
      fromPreview ??
      (dob ? computeEducationTargetYears(planRow, dob) : {
        ug_duration: 4,
        ug_start_year: 0,
        ug_target_year: 0,
        pg_stream: planRow.post_graduation_stream ?? null,
        pg_duration: 0,
        pg_target_year: null,
      });

    return buildEducationChildBlock(planRow, dob, targets, previewRow);
  });
}
