import { render } from "@testing-library/react";
import { cloneElement, isValidElement } from "react";
import type { ReactElement } from "react";
import type * as Recharts from "recharts";
import { describe, expect, it, vi } from "vitest";
import { HousingChart } from "./HousingChart";
import { demographicsStapleton } from "../../test/fixtures/demographics-stapleton";
import type { CensusSnapshot } from "../../types";

// ResponsiveContainer measures its parent, which is always 0x0 in jsdom, so
// Recharts would render nothing. Hand the chart a fixed size instead.
vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof Recharts>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      isValidElement(children)
        ? cloneElement(children, { width: 600, height: 300 } as never)
        : children,
  };
});

const snapshots =
  demographicsStapleton.snapshots as unknown as CensusSnapshot[];

/** The years the x-axis actually renders a tick for. Scoped to the x-axis
 * because Recharts also parks a hidden text-measurement span on document.body,
 * which otherwise shows up as a phantom second match for the last tick. */
function plottedYears(container: HTMLElement): string[] {
  return Array.from(
    container.querySelectorAll(
      ".recharts-xAxis .recharts-cartesian-axis-tick-value",
    ),
  ).map((node) => node.textContent ?? "");
}

describe("HousingChart", () => {
  it("plots the ACS years, which carry an owner/renter split", () => {
    const { container } = render(
      <HousingChart snapshots={snapshots} selectedYear={null} />,
    );

    expect(plottedYears(container)).toEqual([
      "2012",
      "2015",
      "2018",
      "2021",
      "2023",
    ]);
  });

  // H1 (decennial half) — Open. STATUS.md, docs/audits/2026-08-second-audit.
  //
  // HousingChart.tsx:33-37 filters on `total_housing_units != null && (owner
  // != null || renter != null)`. The Census decennial tables return a housing
  // unit total with no tenure split, so 2010 and 2020 are dropped even though
  // the fixture carries real counts for them (1,773 and 2,642 units). Every
  // decade the product is nominally about is structurally invisible.
  //
  // Expected to fail until H1 is fixed. When the fix lands this assertion
  // starts passing and `it.fails` flips it to a failure — that is the signal
  // to delete `.fails`, not to weaken the assertion.
  it.fails(
    "includes the decennial years, which have a housing unit total",
    () => {
      const { container } = render(
        <HousingChart snapshots={snapshots} selectedYear={null} />,
      );

      expect(plottedYears(container)).toContain("2010");
      expect(plottedYears(container)).toContain("2020");
    },
  );
});
