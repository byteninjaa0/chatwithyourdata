/**
 * @vitest-environment jsdom
 */
import { describe, it, expect } from "vitest";
import {
  computeEducationTargetYears,
  formatEducationTargetYearCell,
  parseDuration,
  resolveDuration,
  normalizeCourse,
  ugStartYearFromDob,
  DEFAULT_UG_DURATION,
  COURSE_DURATION,
} from "@/lib/educationTargetYear";

const CHILD_DOB = "2010-06-01";
const UG_START = 2010 + 18;

function child(
  ugStream: string,
  pgStream: string,
  pgDest = "Domestic",
  opts?: { courseDurationUg?: number | string; courseDurationPg?: number | string },
) {
  const row: Record<string, unknown> = {
    graduation_stream: ugStream,
    post_graduation_stream: pgStream,
    post_graduation_destination: pgDest,
  };
  if (opts?.courseDurationUg != null) row.course_duration_ug = opts.courseDurationUg;
  if (opts?.courseDurationPg != null) row.course_duration_pg = opts.courseDurationPg;
  return row;
}

describe("educationTargetYear parity with backend", () => {
  it("ug start year uses dob.year + 18", () => {
    expect(ugStartYearFromDob(CHILD_DOB)).toBe(UG_START);
  });

  it("normalizeCourse: B.Tech / b tech / BTECH -> BTECH", () => {
    expect(normalizeCourse("B.Tech")).toBe("BTECH");
    expect(normalizeCourse("b tech")).toBe("BTECH");
    expect(normalizeCourse("BTECH")).toBe("BTECH");
    expect(COURSE_DURATION.BTECH).toBe(4);
  });

  it("MBBS + MD", () => {
    const t = computeEducationTargetYears(child("MBBS", "MD"), CHILD_DOB);
    expect(t.ug_duration).toBe(5);
    expect(t.ug_target_year).toBe(UG_START + 5);
    expect(t.pg_duration).toBe(3);
    expect(t.pg_target_year).toBe(UG_START + 5 + 3);
  });

  it("BTech / BCom / BBA UG durations", () => {
    expect(computeEducationTargetYears(child("B.Tech", "NA", "NA"), CHILD_DOB).ug_duration).toBe(4);
    expect(computeEducationTargetYears(child("BCom", "NA", "NA"), CHILD_DOB).ug_duration).toBe(3);
    expect(computeEducationTargetYears(child("BBA", "NA", "NA"), CHILD_DOB).ug_duration).toBe(3);
  });

  it("BCom + MBA", () => {
    const t = computeEducationTargetYears(child("BCom", "MBA"), CHILD_DOB);
    expect(t.ug_target_year).toBe(UG_START + 3);
    expect(t.pg_target_year).toBe(UG_START + 3 + 2);
  });

  it("Engineering + MTech", () => {
    const t = computeEducationTargetYears(child("B.Tech", "M.Tech"), CHILD_DOB);
    expect(t.ug_target_year).toBe(UG_START + 4);
    expect(t.pg_target_year).toBe(UG_START + 4 + 2);
  });

  it("NA — no PG target", () => {
    const t = computeEducationTargetYears(child("B.Tech", "NA", "NA"), CHILD_DOB);
    expect(t.pg_target_year).toBeNull();
    expect(t.pg_duration).toBe(0);
  });

  it("UG Other uses course_duration_ug from Airtable", () => {
    const t = computeEducationTargetYears(
      child("Other", "NA", "NA", { courseDurationUg: "6" }),
      CHILD_DOB,
    );
    expect(t.ug_duration).toBe(6);
    expect(t.ug_target_year).toBe(UG_START + 6);
  });

  it("PG Other uses course_duration_pg from Airtable", () => {
    const t = computeEducationTargetYears(
      child("B.Tech", "Other", "Domestic", { courseDurationPg: "2" }),
      CHILD_DOB,
    );
    expect(t.pg_duration).toBe(2);
    expect(t.pg_target_year).toBe(UG_START + 4 + 2);
  });

  it("Other with empty Airtable duration defaults to 4", () => {
    const t = computeEducationTargetYears(child("Other", "NA", "NA"), CHILD_DOB);
    expect(t.ug_duration).toBe(DEFAULT_UG_DURATION);
  });

  it("known stream ignores Airtable duration field", () => {
    const t = computeEducationTargetYears(
      child("MBBS", "MD", "Domestic", { courseDurationUg: 99 }),
      CHILD_DOB,
    );
    expect(t.ug_duration).toBe(5);
  });

  it("resolveDuration helpers", () => {
    expect(parseDuration("5 years", 4)).toBe(5);
    expect(resolveDuration("m.tech", null, 4)).toBe(2);
    expect(resolveDuration("NA", null, 4)).toBe(0);
  });
});

describe("formatEducationTargetYearCell", () => {
  it("shows UG only for NA", () => {
    const text = formatEducationTargetYearCell({
      ug_duration: 4,
      ug_start_year: UG_START,
      ug_target_year: UG_START + 4,
      pg_stream: "NA",
      pg_duration: 0,
      pg_target_year: null,
    });
    expect(text).toBe(`UG ${UG_START + 4} · PG —`);
  });

  it("shows UG and PG years", () => {
    const text = formatEducationTargetYearCell({
      ug_duration: 5,
      ug_start_year: UG_START,
      ug_target_year: UG_START + 5,
      pg_stream: "MD",
      pg_duration: 3,
      pg_target_year: UG_START + 8,
    });
    expect(text).toBe(`UG ${UG_START + 5} · PG ${UG_START + 8}`);
  });
});
