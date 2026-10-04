import { describe, expect, test } from "vitest";

import { setLanguage } from "../src/i18n";
import {
  checkDrafts,
  type Drafts,
  draftsFrom,
  FIELDS,
  guidanceLines,
} from "../src/pages/analysis/analysis_model";
import { defaultAnalysisTuningSettings } from "../src/vehicle_settings";

const t = (key: string, vars?: Record<string, unknown>) =>
  vars ? `${key}:${JSON.stringify(vars)}` : key;

const SAFE: Drafts = {
  speed_uncertainty_pct: "2",
  tire_diameter_uncertainty_pct: "3",
  final_drive_uncertainty_pct: "1",
  gear_uncertainty_pct: "2",
};

describe("analysis drafts", () => {
  test("formats saved values with at most one decimal", () => {
    expect(
      draftsFrom({
        speed_uncertainty_pct: 2,
        tire_diameter_uncertainty_pct: 3.25,
        final_drive_uncertainty_pct: 0.5,
        gear_uncertainty_pct: 1.04,
      }),
    ).toEqual({
      speed_uncertainty_pct: "2",
      tire_diameter_uncertainty_pct: "3.3",
      final_drive_uncertainty_pct: "0.5",
      gear_uncertainty_pct: "1",
    });
  });

  test("saves guided values directly", () => {
    expect(checkDrafts(SAFE, t)).toEqual({
      kind: "ok",
      request: {
        speed_uncertainty_pct: 2,
        tire_diameter_uncertainty_pct: 3,
        final_drive_uncertainty_pct: 1,
        gear_uncertainty_pct: 2,
      },
    });
  });

  test("rejects empty and out-of-bounds values, first field first", () => {
    expect(checkDrafts({ ...SAFE, gear_uncertainty_pct: " " }, t)).toEqual({
      kind: "invalid",
      field: "gear_uncertainty_pct",
      message:
        'settings.analysis.invalid_number:{"field":"settings.gear_slip_uncertainty"}',
    });
    const outOfBounds = checkDrafts(
      {
        ...SAFE,
        speed_uncertainty_pct: "101",
        final_drive_uncertainty_pct: "-1",
      },
      t,
    );
    expect(outOfBounds).toMatchObject({
      kind: "invalid",
      field: "speed_uncertainty_pct",
    });
  });

  test("asks to confirm values outside the guided range", () => {
    const check = checkDrafts(
      { ...SAFE, final_drive_uncertainty_pct: "3", gear_uncertainty_pct: "9" },
      t,
    );
    expect(check.kind).toBe("risky");
    if (check.kind !== "risky") {
      throw new Error("expected a risky draft");
    }
    const lines = check.confirmation.split("\n");
    expect(lines[0]).toBe("settings.analysis.risky_confirm_intro");
    expect(lines).toHaveLength(5);
    expect(lines[1]).toContain('"value":"3"');
    expect(lines[2]).toContain('"value":"9"');
    expect(check.request.gear_uncertainty_pct).toBe(9);
  });

  test("guidance shows the recommended range and the default", () => {
    const gear = FIELDS.find((field) => field.key === "gear_uncertainty_pct");
    if (!gear) {
      throw new Error("missing gear field");
    }
    const [range, defaults] = guidanceLines(gear, t);
    expect(range.value).toBe(
      'settings.analysis.range_value:{"min":"0","max":"4","unit":"%"}',
    );
    expect(defaults.label).toBe("settings.analysis.default_label");
    expect(defaults.value).toMatch(/^\d+(\.\d)?%$/);
  });

  test("shows decimals in the UI language but keeps inputs machine-readable", async () => {
    const gear = FIELDS.find((field) => field.key === "gear_uncertainty_pct");
    if (!gear) {
      throw new Error("missing gear field");
    }
    await setLanguage("nl");
    try {
      // The Pi showed "Standaard 0.2%" on the Dutch Analysis page.
      expect(guidanceLines(gear, t)[1].value).toBe("0,2%");
      // A number input only accepts "." whatever the page language.
      expect(
        draftsFrom(defaultAnalysisTuningSettings).gear_uncertainty_pct,
      ).toBe("0.2");
      const risky = checkDrafts({ ...SAFE, gear_uncertainty_pct: "4.5" }, t);
      expect(risky.kind === "risky" && risky.confirmation).toContain(
        '"value":"4,5"',
      );
    } finally {
      await setLanguage("en");
    }
  });
});
