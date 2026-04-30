import { expect, test } from "vitest";
import type { HistoryEntry } from "../src/api/types";
import { buildHistoryTableRowsViewModel } from "../src/app/views/history_table_presenters";
import type { RunDetail } from "../src/app/ui_app_state";

function testTranslation(key: string, vars?: Record<string, unknown>): string {
  return vars ? `${key}:${JSON.stringify(vars)}` : key;
}

function defaultDetail(detail: Partial<RunDetail> = {}): RunDetail {
  return {
    preview: null,
    previewLoading: false,
    previewError: "",
    insights: null,
    insightsLoading: false,
    insightsError: "",
    pdfLoading: false,
    pdfError: "",
    ...detail,
  };
}

function historyListRun(
  runId: string,
  overrides: Partial<HistoryEntry> = {},
): HistoryEntry {
  return {
    run_id: runId,
    start_time_utc: "2026-01-01T00:00:00Z",
    end_time_utc: "2026-01-01T00:00:12Z",
    sample_count: 2048,
    status: "complete",
    car_name: "Track Car",
    error_message: null,
    ...overrides,
  } as HistoryEntry;
}

test("history summary chips expose stable presenter-owned keys", () => {
  const rows = buildHistoryTableRowsViewModel({
    runs: [
      historyListRun("run-001"),
      historyListRun("run-002", {
        status: "error",
        error_message: "history.error.capture_failed",
      }),
    ],
    expandedRunId: null,
    runDetailsById: {
      "run-001": defaultDetail(),
      "run-002": defaultDetail(),
    },
    t: testTranslation,
    fmt: (value, digits = 0) => Number(value).toFixed(digits),
    fmtTs: (iso) => iso,
    formatInt: (value) => String(value),
  });

  expect(rows[0].summaryChips.map((chip) => chip.key)).toEqual(["status"]);
  expect(rows[1].summaryChips.map((chip) => chip.key)).toEqual([
    "status",
    "error-message",
  ]);
});
