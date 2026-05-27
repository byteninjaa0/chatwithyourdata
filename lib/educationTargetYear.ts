/**
 * Mirrors Financial_Planning/education_target_years.py exactly for UI preview.
 */

export const UG_START_AGE = 18;
export const DEFAULT_UG_DURATION = 4;

export const COURSE_DURATION: Record<string, number> = {
  BTECH: 4,
  MBBS: 5,
  BCOM: 3,
  BBA: 3,
  MTECH: 2,
  MBA: 2,
  MD: 3,
};

export type EducationChildInput = {
  graduationStream?: unknown;
  graduation_stream?: unknown;
  courseDurationUg?: unknown;
  course_duration_ug?: unknown;
  courseDuration?: unknown;
  course_duration?: unknown;
  postGraduationStream?: unknown;
  post_graduation_stream?: unknown;
  courseDurationPg?: unknown;
  course_duration_pg?: unknown;
  pgCourseDuration?: unknown;
  post_graduation_course_duration?: unknown;
  postGraduationDestination?: unknown;
  post_graduation_destination?: unknown;
  dob?: string;
};

export type EducationTargetYears = {
  ug_duration: number;
  ug_start_year: number;
  ug_target_year: number;
  pg_stream: unknown;
  pg_duration: number;
  pg_target_year: number | null;
};

function field<T>(child: EducationChildInput, ...keys: string[]): T | undefined {
  const c = child as Record<string, unknown>;
  for (const k of keys) {
    if (c[k] != null) return c[k] as T;
  }
  return undefined;
}

export function normalizeCourse(value: unknown): string {
  return String(value ?? "")
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "");
}

export function parseDuration(value: unknown, fallback: number): number {
  if (value == null) return fallback;
  if (typeof value === "number") return Math.trunc(value);
  const d = String(value).replace(/\D/g, "");
  return d ? parseInt(d, 10) : fallback;
}

function isEmptyDuration(value: unknown): boolean {
  if (value == null) return true;
  if (typeof value === "string" && !value.trim()) return true;
  return false;
}

export function resolveDuration(
  courseValue: unknown,
  airtableOther: unknown,
  def: number,
): number {
  const k = normalizeCourse(courseValue);
  if (k === "NA") return 0;
  if (k in COURSE_DURATION) return COURSE_DURATION[k];
  if (k === "OTHER") {
    if (isEmptyDuration(airtableOther)) return def;
    return parseDuration(airtableOther, def);
  }
  return def;
}

/** @deprecated use normalizeCourse */
export function normalizePgStreamKey(stream: unknown): string {
  return normalizeCourse(stream);
}

/** @deprecated use resolveDuration */
export function pgDurationFromStream(
  stream: unknown,
  ugStyle: number,
  defaultOther: number,
): number {
  return resolveDuration(stream, ugStyle, defaultOther);
}

export function ugStartYearFromDob(dob: string, startAge: number = UG_START_AGE): number {
  const d = new Date(dob);
  if (Number.isNaN(d.getTime())) return NaN;
  return d.getFullYear() + startAge;
}

function ugOtherDuration(child: EducationChildInput): unknown {
  return field(child, "courseDurationUg", "course_duration_ug", "courseDuration", "course_duration");
}

function pgOtherDuration(child: EducationChildInput): unknown {
  return field(
    child,
    "courseDurationPg",
    "course_duration_pg",
    "pgCourseDuration",
    "post_graduation_course_duration",
  );
}

export function computeEducationTargetYears(
  child: EducationChildInput,
  dob: string,
): EducationTargetYears {
  const ugStartYear = ugStartYearFromDob(dob);
  const ugStream = field(child, "graduationStream", "graduation_stream");
  const pgStream = field(child, "postGraduationStream", "post_graduation_stream");
  const pgDestination = field(child, "postGraduationDestination", "post_graduation_destination");

  const ugDuration = resolveDuration(ugStream, ugOtherDuration(child), DEFAULT_UG_DURATION);
  const ugTargetYear = ugStartYear + ugDuration;

  let pgDuration = resolveDuration(pgStream, pgOtherDuration(child), DEFAULT_UG_DURATION);

  let pgTargetYear: number | null = null;
  if (pgDuration > 0 && normalizeCourse(pgStream) !== "NA") {
    const dest = String(pgDestination ?? "")
      .trim()
      .toUpperCase();
    if (dest && dest !== "NA" && dest !== "NONE") {
      pgTargetYear = ugTargetYear + pgDuration;
    } else {
      pgDuration = 0;
    }
  } else {
    pgDuration = 0;
  }

  return {
    ug_duration: ugDuration,
    ug_start_year: ugStartYear,
    ug_target_year: ugTargetYear,
    pg_stream: pgStream ?? null,
    pg_duration: pgDuration,
    pg_target_year: pgTargetYear,
  };
}

export function formatEducationTargetYearCell(targets: EducationTargetYears): string {
  const ug = `UG ${targets.ug_target_year}`;
  if (targets.pg_target_year == null) return `${ug} · PG —`;
  return `${ug} · PG ${targets.pg_target_year}`;
}
