import { expect, test } from "vitest";
import { defaultAnalysisSettings } from "../src/constants";
import {
  composeVehicleSettings,
  defaultAnalysisTuningSettings,
  defaultCarAspectSettings,
  mergeAnalysisTuningSettings,
  mergeCarAspectSettings,
} from "../src/vehicle_settings";

test("vehicle settings carry every backend analysis setting exactly once", () => {
  expect(
    composeVehicleSettings(
      defaultCarAspectSettings,
      defaultAnalysisTuningSettings,
    ),
  ).toEqual(defaultAnalysisSettings);

  const patch = Object.fromEntries(
    Object.keys(defaultAnalysisSettings).map((key, index) => [
      key,
      1000 + index,
    ]),
  );
  expect(
    composeVehicleSettings(
      mergeCarAspectSettings(defaultCarAspectSettings, patch),
      mergeAnalysisTuningSettings(defaultAnalysisTuningSettings, patch),
    ),
  ).toEqual(patch);
});
