/**
 * @vitest-environment jsdom
 */
import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { EducationPlanningSection } from "@/components/EducationPlanningSection";
import type { EducationChildBlock } from "@/lib/educationPlanningView";

const UG_START = 2010 + 18;

const withPgPrePlan: EducationChildBlock = {
  name: "Asha",
  age: 16,
  hasPg: true,
  ug: {
    stream: "MBBS",
    destination: "Domestic",
    duration: 5,
    targetYear: UG_START + 5,
    currentCost: null,
    futureCost: null,
    corpusGap: null,
    status: null,
  },
  pg: {
    stream: "MD",
    destination: "Domestic",
    duration: 3,
    targetYear: UG_START + 8,
    currentCost: null,
    futureCost: null,
    corpusGap: null,
    status: null,
  },
};

const withPgPostPlan: EducationChildBlock = {
  ...withPgPrePlan,
  ug: { ...withPgPrePlan.ug, futureCost: 1_500_000 },
  pg: { ...withPgPrePlan.pg!, futureCost: 2_000_000 },
};

const naOnly: EducationChildBlock = {
  name: "Ravi",
  age: 14,
  hasPg: false,
  ug: {
    stream: "B.Tech",
    destination: "Domestic",
    duration: 4,
    targetYear: 2012 + 18 + 4,
    currentCost: null,
    futureCost: null,
    corpusGap: null,
    status: null,
  },
  pg: null,
};

const EXPECTED_HEADERS = ["Stream", "Course Duration", "Target Year", "Target Amount"];
const REMOVED_HEADERS = ["Current Cost", "Future Cost", "Funding Status", "Particulars"];

function tableCellCounts(table: HTMLTableElement) {
  const headers = within(table).getAllByRole("columnheader");
  const cells = within(table).getAllByRole("cell");
  return { headers: headers.length, cells: cells.length };
}

describe("EducationPlanningSection", () => {
  it("UG table has 4 horizontal columns and no removed columns", () => {
    render(<EducationPlanningSection blocks={[withPgPrePlan]} />);
    const ugSection = document.querySelector(".ug-section")!;
    const table = ugSection.querySelector("table") as HTMLTableElement;
    const { headers, cells } = tableCellCounts(table);
    expect(headers).toBe(4);
    expect(cells).toBe(4);
    for (const h of EXPECTED_HEADERS) {
      expect(within(table).getByRole("columnheader", { name: h })).toBeInTheDocument();
    }
    for (const h of REMOVED_HEADERS) {
      expect(within(table).queryByRole("columnheader", { name: h })).not.toBeInTheDocument();
    }
    expect(screen.getByText("5 yrs")).toBeInTheDocument();
    expect(screen.getByText(String(UG_START + 5))).toBeInTheDocument();
  });

  it("child with PG: PG table has same 4 columns", () => {
    render(<EducationPlanningSection blocks={[withPgPrePlan]} />);
    const pgSection = document.querySelector(".pg-section")!;
    const table = pgSection.querySelector("table") as HTMLTableElement;
    const { headers, cells } = tableCellCounts(table);
    expect(headers).toBe(4);
    expect(cells).toBe(4);
    expect(within(table).getByRole("columnheader", { name: "Target Amount" })).toBeInTheDocument();
    expect(screen.getByText("3 yrs")).toBeInTheDocument();
    expect(screen.getByText(String(UG_START + 8))).toBeInTheDocument();
  });

  it("NA child: PG table absent, note present", () => {
    render(<EducationPlanningSection blocks={[naOnly]} />);
    expect(document.querySelector(".pg-section")).toBeNull();
    expect(
      screen.getByText(/No postgraduate education planned for Ravi/),
    ).toBeInTheDocument();
  });

  it("Target Amount shows em dash pre-plan and INR post-plan", () => {
    const { rerender } = render(<EducationPlanningSection blocks={[withPgPrePlan]} />);
    const ugTable = document.querySelector(".ug-section table") as HTMLTableElement;
    expect(within(ugTable).getAllByRole("cell")[3].textContent).toBe("—");

    rerender(<EducationPlanningSection blocks={[withPgPostPlan]} />);
    expect(screen.getByText("₹15,00,000")).toBeInTheDocument();
    expect(screen.getByText("₹20,00,000")).toBeInTheDocument();
  });

  it("MBBS shows 5 yrs in UG table; Other shows Airtable duration", () => {
    render(<EducationPlanningSection blocks={[withPgPrePlan]} />);
    expect(screen.getByText("5 yrs")).toBeInTheDocument();

    const otherChild: EducationChildBlock = {
      name: "Sam",
      age: 10,
      hasPg: false,
      ug: {
        stream: "Other",
        destination: "Domestic",
        duration: 6,
        targetYear: 2015 + 18 + 6,
        currentCost: null,
        futureCost: null,
        corpusGap: null,
        status: null,
      },
      pg: null,
    };
    render(<EducationPlanningSection blocks={[otherChild]} />);
    expect(screen.getByText("6 yrs")).toBeInTheDocument();
  });

  it("renders separate blocks for multiple children", () => {
    render(<EducationPlanningSection blocks={[withPgPrePlan, naOnly]} />);
    expect(document.querySelectorAll(".child-education-block")).toHaveLength(2);
  });
});
