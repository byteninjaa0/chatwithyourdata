import { describe, it, expect } from "vitest";
import { buildEducationPlanningBlocks, childAgeFromDob } from "@/lib/educationPlanningView";
import { computeEducationTargetYears } from "@/lib/educationTargetYear";

const CHILD_DOB = "2010-06-01";
const UG_START = 2010 + 18;

const kids = [{ child_name: "Asha", child_dob: CHILD_DOB }];

describe("buildEducationPlanningBlocks", () => {
  it("MBBS+MD: UG duration 5 from stream mapping pre-plan", () => {
    const plans = [
      {
        name_of_kid: "Asha",
        dob: CHILD_DOB,
        graduation_stream: "MBBS",
        graduation_destination: "Domestic",
        post_graduation_stream: "MD",
        post_graduation_destination: "Domestic",
      },
    ];
    const blocks = buildEducationPlanningBlocks(plans, kids);
    expect(blocks).toHaveLength(1);
    expect(blocks[0].ug.duration).toBe(5);
    expect(blocks[0].ug.targetYear).toBe(UG_START + 5);
    expect(blocks[0].hasPg).toBe(true);
    expect(blocks[0].pg?.duration).toBe(3);
    expect(blocks[0].pg?.targetYear).toBe(UG_START + 5 + 3);
  });

  it("NA stream: UG only, no PG block", () => {
    const plans = [
      {
        name_of_kid: "Asha",
        dob: CHILD_DOB,
        graduation_stream: "B.Tech",
        post_graduation_stream: "NA",
        post_graduation_destination: "NA",
      },
    ];
    const blocks = buildEducationPlanningBlocks(plans, kids);
    expect(blocks[0].hasPg).toBe(false);
    expect(blocks[0].pg).toBeNull();
  });

  it("multiple children: one block each", () => {
    const plans = [
      {
        name_of_kid: "Asha",
        dob: CHILD_DOB,
        graduation_stream: "MBBS",
        post_graduation_stream: "MD",
        post_graduation_destination: "Domestic",
      },
      {
        name_of_kid: "Ravi",
        dob: "2012-01-15",
        graduation_stream: "BCom",
        post_graduation_stream: "NA",
        post_graduation_destination: "NA",
      },
    ];
    const blocks = buildEducationPlanningBlocks(plans, [
      ...kids,
      { child_name: "Ravi", child_dob: "2012-01-15" },
    ]);
    expect(blocks).toHaveLength(2);
    expect(blocks.map((b) => b.name)).toEqual(["Asha", "Ravi"]);
    expect(blocks[1].ug.duration).toBe(3);
  });

  it("Other UG uses course_duration_ug from Airtable", () => {
    const plans = [
      {
        name_of_kid: "Asha",
        dob: CHILD_DOB,
        graduation_stream: "Other",
        course_duration_ug: 6,
        post_graduation_stream: "NA",
        post_graduation_destination: "NA",
      },
    ];
    const blocks = buildEducationPlanningBlocks(plans, kids);
    expect(blocks[0].ug.duration).toBe(6);
  });

  it("post-plan preview supplies costs; targets match computeEducationTargetYears", () => {
    const planRow = {
      name_of_kid: "Asha",
      dob: CHILD_DOB,
      graduation_stream: "MBBS",
      post_graduation_stream: "MD",
      post_graduation_destination: "Domestic",
    };
    const expected = computeEducationTargetYears(planRow, CHILD_DOB);
    const blocks = buildEducationPlanningBlocks([planRow], kids, {
      targetsPreview: [{ child_name: "Asha", ...expected }],
      planningPreview: [
        {
          child_name: "Asha",
          ...expected,
          ug_future_cost: 1_500_000,
          pg_future_cost: 2_000_000,
        },
      ],
    });
    expect(blocks[0].ug.targetYear).toBe(expected.ug_target_year);
    expect(blocks[0].pg?.targetYear).toBe(expected.pg_target_year);
    expect(blocks[0].ug.futureCost).toBe(1_500_000);
  });

  it("missing optional fields render nulls without crash", () => {
    const blocks = buildEducationPlanningBlocks(
      [{ name_of_kid: "Unknown", graduation_stream: "Other" }],
      [],
    );
    expect(blocks[0].ug.currentCost).toBeNull();
    expect(blocks[0].age).toBeNull();
  });
});

describe("childAgeFromDob", () => {
  it("uses year difference only", () => {
    expect(childAgeFromDob(CHILD_DOB, 2026)).toBe(16);
  });
});
