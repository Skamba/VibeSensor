import { expect, test } from "vitest";
import { defaultAnalysisSettings } from "../src/constants";
import {
  defaultAnalysisTuningSettings,
  mergeAnalysisTuningSettings,
} from "../src/vehicle_settings";

test("tuning settings mirror the backend defaults; car references have none", () => {
  const { tire_deflection_factor, ...tuning } = defaultAnalysisSettings;
  expect(tire_deflection_factor).toBeGreaterThan(0);
  expect(defaultAnalysisTuningSettings).toEqual(tuning);
  expect(defaultAnalysisSettings).not.toHaveProperty("final_drive_ratio");

  const patch = Object.fromEntries(
    Object.keys(tuning).map((key, index) => [key, 1000 + index]),
  );
  expect(
    mergeAnalysisTuningSettings(defaultAnalysisTuningSettings, {
      ...patch,
      speed_uncertainty_pct: null,
    }),
  ).toEqual({
    ...patch,
    speed_uncertainty_pct: defaultAnalysisTuningSettings.speed_uncertainty_pct,
  });
});
