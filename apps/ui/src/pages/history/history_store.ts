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
/** The latest diagnosis request per run: an older response is dropped. */
const requestSeq = new Map<string, number>();

function updateDetail(runId: string, patch: Partial<RunDetail>): void {
  details.value = {
    ...details.value,
    [runId]: { ...(details.value[runId] ?? EMPTY_RUN_DETAIL), ...patch },
  };
}

function dropDetail(runId: string): void {
  requestSeq.delete(runId);
  const { [runId]: _dropped, ...rest } = details.value;
  details.value = rest;
}

/** Loads the run's diagnosis: the row's title and the opened page. A reload
 * keeps the one already shown until the new one arrives, and supersedes any
 * load still running (worded in the previous language). */
async function loadDiagnosis(runId: string, force = false): Promise<void> {
  const detail = details.value[runId] ?? EMPTY_RUN_DETAIL;
  if (!force && (detail.loading || detail.summary)) {
    return;
  }
  const seq = (requestSeq.get(runId) ?? 0) + 1;
  requestSeq.set(runId, seq);
  const current = () => requestSeq.get(runId) === seq;
  updateDetail(runId, { loading: true, error: "" });
  try {
    const response = await getHistoryInsights(runId, lang.value);
    if (current()) {
      updateDetail(runId, {
        summary: response.status === "complete" ? response : null,
      });
    }
  } catch (error) {
    if (current()) {
      updateDetail(runId, {
        error: errorMessage(error, t("report.unable_load_insights")),
      });
    }
  } finally {
    if (current()) {
      updateDetail(runId, { loading: false });
    }
  }
}

let prefetchToken = 0;

/** Loads the diagnosis of every analysed run, a few at a time. */
async function prefetchDiagnoses(force = false): Promise<void> {
  const token = ++prefetchToken;
  const ready = runs.value.filter(postAnalysisReady);
  for (let index = 0; index < ready.length; index += PREFETCH_CONCURRENCY) {
    if (token !== prefetchToken) {
      return;
    }
    await Promise.all(
      ready
        .slice(index, index + PREFETCH_CONCURRENCY)
        .map((run) => loadDiagnosis(run.run_id, force)),
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
  void prefetchDiagnoses();
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

/** Opens or closes a run's diagnosis; a closed run keeps its loaded title. */
export function toggleRun(runId: string): void {
  if (expandedRunId.value === runId) {
    expandedRunId.value = null;
    return;
  }
  expandedRunId.value = runId;
  void loadDiagnosis(runId);
}

export function reloadDiagnosis(runId: string): Promise<void> {
  return loadDiagnosis(runId, true);
}

// A language or speed-unit switch reloads every diagnosis: the server words
// them in both.
let lastWording = `${lang.peek()}|${speedUnit.peek()}`;
effect(() => {
  const next = `${lang.value}|${speedUnit.value}`;
  if (next === lastWording) {
    return;
  }
  lastWording = next;
  void prefetchDiagnoses(true);
});

/** Deletes one run after confirmation; `name` is its title in the list. */
export async function deleteRun(runId: string, name: string): Promise<void> {
  if (!(await requestConfirmation(t("history.delete_confirm", { name })))) {
    return;
  }
  try {
    await deleteHistoryRun(runId);
  } catch (error) {
    showError(errorMessage(error, t("history.delete_failed")));
    return;
  }
  batch(() => {
    if (expandedRunId.value === runId) {
      expandedRunId.value = null;
    }
    dropDetail(runId);
  });
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
      batch(() => {
        if (expandedRunId.value === runId) {
          expandedRunId.value = null;
        }
        dropDetail(runId);
      });
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
