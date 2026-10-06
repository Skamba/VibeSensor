import { batch, effect, signal } from "@preact/signals";

import {
  deleteHistoryRun,
  getHistory,
  getHistoryInsights,
  historyReportPdfUrl,
} from "../../api/history";
import type { HistoryEntry } from "../../api/types";
import {
  errorMessage,
  onViewEnter,
  requestConfirmation,
  showError,
  speedUnit,
} from "../../app_store";
import { lang, t } from "../../i18n";
import { runsChanged } from "../../live_store";
import { downloadFile } from "./download";
import {
  EMPTY_RUN_DETAIL,
  postAnalysisReady,
  type RunDetail,
} from "./history_model";

const PREFETCH_CONCURRENCY = 3;

export const runs = signal<HistoryEntry[]>([]);
export const expandedRunId = signal<string | null>(null);
export const details = signal<Record<string, RunDetail>>({});
export const deleteAllInFlight = signal(false);

function updateDetail(runId: string, patch: Partial<RunDetail>): void {
  details.value = {
    ...details.value,
    [runId]: { ...(details.value[runId] ?? EMPTY_RUN_DETAIL), ...patch },
  };
}

function dropDetail(runId: string): void {
  const { [runId]: _dropped, ...rest } = details.value;
  details.value = rest;
}

function collapse(): void {
  const previous = expandedRunId.value;
  batch(() => {
    expandedRunId.value = null;
    if (previous) {
      dropDetail(previous);
    }
  });
}

/** Loads the run's diagnosis into `preview` (row summary) or `insights`. */
async function loadDiagnosis(
  runId: string,
  target: "preview" | "insights",
  force = false,
): Promise<void> {
  const detail = details.value[runId] ?? EMPTY_RUN_DETAIL;
  const loadingKey =
    target === "preview" ? "previewLoading" : "insightsLoading";
  const errorKey = target === "preview" ? "previewError" : "insightsError";
  if (
    !force &&
    (detail[loadingKey] || (target === "preview" && detail.preview))
  ) {
    return;
  }
  updateDetail(runId, { [loadingKey]: true, [errorKey]: "" });
  try {
    const response = await getHistoryInsights(runId, lang.value);
    updateDetail(runId, {
      [target]: response.status === "complete" ? response : null,
    });
  } catch (error) {
    updateDetail(runId, {
      [errorKey]: errorMessage(error, t("report.unable_load_insights")),
    });
  } finally {
    updateDetail(runId, { [loadingKey]: false });
  }
}

let prefetchToken = 0;

/** Loads row summaries for analysed runs, a few at a time. */
async function prefetchPreviews(): Promise<void> {
  const token = ++prefetchToken;
  const ready = runs.value.filter(postAnalysisReady);
  for (let index = 0; index < ready.length; index += PREFETCH_CONCURRENCY) {
    if (token !== prefetchToken) {
      return;
    }
    await Promise.all(
      ready
        .slice(index, index + PREFETCH_CONCURRENCY)
        .map((run) => loadDiagnosis(run.run_id, "preview")),
    );
  }
}

/** Reloads the run list; failures keep the current list. */
export async function refreshHistory(): Promise<void> {
  try {
    runs.value = (await getHistory()).runs ?? [];
  } catch {
    return;
  }
  void prefetchPreviews();
}

let loaded = false;
onViewEnter("historyView", async () => {
  if (!loaded) {
    await refreshHistory();
    loaded = true;
  }
});

// A recording started, stopped, or finished analysis on the dashboard.
let seenRunsChange = runsChanged.peek();
effect(() => {
  const change = runsChanged.value;
  if (change !== seenRunsChange) {
    seenRunsChange = change;
    void refreshHistory();
  }
});

export function toggleRun(runId: string): void {
  const wasExpanded = expandedRunId.value === runId;
  collapse();
  if (!wasExpanded) {
    expandedRunId.value = runId;
    void loadDiagnosis(runId, "preview");
  }
}

export function reloadInsights(runId: string): Promise<void> {
  return loadDiagnosis(runId, "insights", true);
}

// A language or speed-unit switch reloads the open diagnosis: the server words
// its warnings in both.
let lastWording = `${lang.peek()}|${speedUnit.peek()}`;
effect(() => {
  const next = `${lang.value}|${speedUnit.value}`;
  const runId = expandedRunId.peek();
  if (next === lastWording) {
    return;
  }
  lastWording = next;
  if (!runId) {
    return;
  }
  const hadInsights = Boolean(details.peek()[runId]?.insights);
  dropDetail(runId);
  void loadDiagnosis(runId, "preview", true).then(() =>
    hadInsights ? loadDiagnosis(runId, "insights", true) : undefined,
  );
});

export async function deleteRun(runId: string): Promise<void> {
  if (
    !(await requestConfirmation(t("history.delete_confirm", { name: runId })))
  ) {
    return;
  }
  try {
    await deleteHistoryRun(runId);
  } catch (error) {
    showError(errorMessage(error, t("history.delete_failed")));
    return;
  }
  if (expandedRunId.value === runId) {
    collapse();
  }
  await refreshHistory();
}

export async function deleteAllRuns(): Promise<void> {
  const ids = runs.value.map((run) => run.run_id).filter(Boolean);
  if (
    !ids.length ||
    !(await requestConfirmation(
      t("history.delete_all_confirm", { count: ids.length }),
    ))
  ) {
    return;
  }
  deleteAllInFlight.value = true;
  let failed = 0;
  let firstError = "";
  for (const runId of ids) {
    try {
      await deleteHistoryRun(runId);
      if (expandedRunId.value === runId) {
        collapse();
      }
      dropDetail(runId);
    } catch (error) {
      failed += 1;
      firstError ||= errorMessage(error, t("history.delete_failed"));
    }
  }
  deleteAllInFlight.value = false;
  await refreshHistory();
  if (failed > 0) {
    const summary = t("history.delete_all_partial", {
      deleted: ids.length - failed,
      total: ids.length,
      failed,
    });
    showError(firstError ? `${summary}\n${firstError}` : summary);
  }
}

export async function downloadReport(runId: string): Promise<void> {
  if (details.value[runId]?.pdfLoading) {
    return;
  }
  updateDetail(runId, { pdfLoading: true, pdfError: "" });
  try {
    await downloadFile(
      historyReportPdfUrl(runId, lang.value),
      `${runId}_report.pdf`,
    );
  } catch (error) {
    updateDetail(runId, {
      pdfError: errorMessage(error, t("history.pdf_failed")),
    });
  } finally {
    updateDetail(runId, { pdfLoading: false });
  }
}
