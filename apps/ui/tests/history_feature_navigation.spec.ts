import { expect, test } from "vitest";
import {
  createFeatureHarness,
  installHistoryFeatureTestLifecycle,
} from "./history_feature_test_support";

installHistoryFeatureTestLifecycle();

test("history feature routes the open-live action to dashboard navigation", () => {
  const { feature, getLatestHandlers, primaryViewActivations } =
    createFeatureHarness();
  feature.bindHandlers();

  getLatestHandlers()?.onTableInteraction({ type: "open-live" });

  expect(primaryViewActivations).toEqual(["dashboardView"]);
});
