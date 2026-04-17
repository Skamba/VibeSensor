import assert from "node:assert/strict";

import type { HistoryEntry } from "../src/api/types";
import type { RunDetail } from "../src/app/ui_app_state";
import { createHistoryTableRowsMemo } from "../src/app/views/history_table_presenters";

function testTranslation(key: string, vars?: Record<string, unknown>): string {
  return vars ? `${key}:${JSON.stringify(vars)}` : key;
}

function historyListRun(runId: string): HistoryEntry {
  return {
    run_id: runId,
    start_time_utc: "2026-01-01T00:00:00Z",
    end_time_utc: "2026-01-01T00:00:12Z",
    sample_count: 42,
    status: "complete",
    car_name: "Track Car",
    error_message: null,
  } as HistoryEntry;
}

function defaultDetail(detail: Partial<RunDetail>): RunDetail {
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

async function runHistoryTableRowsMemoTest(): Promise<void> {
  const memoizeRows = createHistoryTableRowsMemo();
  const runs = [historyListRun("run-001")];
  const runDetailsById = {
    "run-001": defaultDetail({}),
  };
  const fmt = (value: number, digits = 0) => Number(value).toFixed(digits);
  const fmtTs = (iso: string) => iso;
  const formatInt = (value: number) => String(value);
  const historyExportUrl = (runId: string) => `/api/history/${runId}/export`;

  const firstRows = memoizeRows({
    runs,
    expandedRunId: null,
    runDetailsById,
    t: testTranslation,
    fmt,
    fmtTs,
    formatInt,
    historyExportUrl,
  });
  const secondRows = memoizeRows({
    runs,
    expandedRunId: null,
    runDetailsById,
    t: testTranslation,
    fmt,
    fmtTs,
    formatInt,
    historyExportUrl,
  });

  assert.equal(firstRows, secondRows);
  assert.equal(firstRows[0]?.isExpanded, false);

  runDetailsById["run-001"].previewLoading = true;
  const loadingRows = memoizeRows({
    runs,
    expandedRunId: null,
    runDetailsById,
    t: testTranslation,
    fmt,
    fmtTs,
    formatInt,
    historyExportUrl,
  });

  assert.notEqual(loadingRows, firstRows);
  assert.equal(loadingRows[0]?.summaryHeadline, "history.row_summary_loading");

  const expandedRows = memoizeRows({
    runs,
    expandedRunId: "run-001",
    runDetailsById,
    t: testTranslation,
    fmt,
    fmtTs,
    formatInt,
    historyExportUrl,
  });

  assert.notEqual(expandedRows, firstRows);
  assert.equal(expandedRows[0]?.isExpanded, true);
}

await runHistoryTableRowsMemoTest();
console.log("PASS history table rows memoize stable presenter inputs");
