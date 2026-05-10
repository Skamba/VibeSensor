import { expect, test } from "vitest";
import type { HistoryInsightsPayload } from "../src/api/types";
import { buildHistoryHeatmapViewModel } from "../src/app/views/history_heatmap_presenter";
import {
  makeHistoryInsightsPayload,
  makeLocationIntensityRow,
} from "./history_payload_test_support";

function makeSummary(
  rows: HistoryInsightsPayload["sensor_intensity_by_location"],
): HistoryInsightsPayload {
  return makeHistoryInsightsPayload({
    run_id: "run-001",
    start_time_utc: "2026-01-01T00:00:00Z",
    duration_s: 12,
    sensor_count_used: rows.length,
    sensor_intensity_by_location: rows,
  });
}

test("buildHistoryHeatmapViewModel uses the final normalized location values for strongest and extras", () => {
  const heatmap = buildHistoryHeatmapViewModel(
    makeSummary([
      makeLocationIntensityRow({
        location: "Front Left Wheel",
        p50_intensity_db: 8,
        p95_intensity_db: 30,
        max_intensity_db: 32,
      }),
      makeLocationIntensityRow({
        location: "front_left_wheel",
        p50_intensity_db: 8,
        p95_intensity_db: 10,
        max_intensity_db: 12,
      }),
      makeLocationIntensityRow({
        location: "Front Right Wheel",
        p50_intensity_db: 8,
        p95_intensity_db: 24,
        max_intensity_db: 26,
      }),
      makeLocationIntensityRow({
        location: "Custom Tunnel Mount",
        p50_intensity_db: 8,
        p95_intensity_db: 16,
        max_intensity_db: 18,
      }),
    ]),
    {
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      t: (key) => key,
    },
  );

  expect(
    heatmap.zones.find((zone) => zone.key === "front-left wheel"),
  ).toMatchObject({
    label: "front_left_wheel",
    strongest: false,
    valueLabel: "10.0 dB",
  });
  expect(
    heatmap.zones.find((zone) => zone.key === "front-right wheel"),
  ).toMatchObject({
    label: "Front Right Wheel",
    strongest: true,
    valueLabel: "24.0 dB",
  });
  expect(heatmap.extras).toEqual(["Custom Tunnel Mount · 16.0 dB"]);
});
