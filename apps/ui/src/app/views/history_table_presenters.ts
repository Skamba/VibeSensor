import type { HistoryEntry } from "../../api/types";
import type { RunDetail } from "../ui_app_state";
import { buildHistoryDetailsViewModel } from "./history_detail_presenter";
import {
  EMPTY_RUN_DETAIL,
  confidenceText,
  formatSourceLabel,
  historyRowCarName,
  historyRowDurationSeconds,
  historyReportReady,
  historyRowStatusBadge,
  historyPostAnalysisReady,
  historyRowSummary,
  isInconclusiveFinding,
  summarizeFindings,
  type HistoryRowSummary,
  type PresenterParams,
} from "./history_presenter_shared";
import type {
  HistoryCollapsedActionViewModel,
  HistoryRowViewModel,
  HistorySummaryChipViewModel,
} from "./history_table_models";
import type {
  HistoryPanelTableRenderModel,
  HistoryTableViewParams,
} from "./history_table_view";

function buildSummaryChips(
  run: HistoryEntry,
  detail: RunDetail,
  params: Pick<PresenterParams, "t">,
): HistorySummaryChipViewModel[] {
  const { t } = params;
  const statusBadge = historyRowStatusBadge(run, detail, t);
  const chips: HistorySummaryChipViewModel[] = [
    { key: "status", text: statusBadge.label, tone: statusBadge.tone },
  ];
  if (
    (run.lifecycle?.stage === "post_analysis_degraded" ||
      run.status === "error") &&
    run.error_message
  ) {
    chips.push({
      key: "error-message",
      text: run.error_message,
      tone: "muted",
    });
  }
  return chips;
}

function buildHistoryRowSummary(
  run: HistoryEntry,
  detail: RunDetail,
  params: Pick<PresenterParams, "fmt" | "formatInt" | "t">,
): HistoryRowSummary {
  const { fmt, formatInt, t } = params;
  const summary = historyRowSummary(detail);
  const primaryFinding = summarizeFindings(summary)[0] ?? null;
  const source =
    summary?.most_likely_origin?.suspected_source ||
    primaryFinding?.suspected_source ||
    "";
  const sourceLabel =
    primaryFinding && isInconclusiveFinding(primaryFinding)
      ? t("history.row_source_inconclusive")
      : source
        ? formatSourceLabel(source, t)
        : "";
  const analysisReady = historyPostAnalysisReady(run);
  const headline =
    sourceLabel ||
    (analysisReady &&
    (detail.previewLoading || detail.insightsLoading || summary === null)
      ? t("history.row_summary_loading")
      : analysisReady && summary
        ? t("history.row_no_findings")
        : historyRowStatusBadge(run, detail, t).label);
  const metaParts: string[] = [];
  if (primaryFinding) {
    metaParts.push(confidenceText(primaryFinding, params));
  }
  const durationSeconds = historyRowDurationSeconds(run, detail);
  if (durationSeconds !== null) {
    metaParts.push(
      `${t("history.summary_size")}: ${fmt(durationSeconds, 1)} s`,
    );
  }
  const sensorCount = Number(summary?.sensor_count_used);
  if (Number.isFinite(sensorCount) && sensorCount > 0) {
    metaParts.push(
      `${t("history.summary_sensor_count")}: ${formatInt(sensorCount)}`,
    );
  }
  if (metaParts.length === 0 && run.status === "error" && run.error_message) {
    metaParts.push(run.error_message);
  }
  return {
    headline,
    meta: metaParts.length ? metaParts.join(" · ") : null,
  };
}

function buildCollapsedAction(
  run: HistoryEntry,
  detail: RunDetail,
  t: PresenterParams["t"],
): HistoryCollapsedActionViewModel {
  if (!historyReportReady(run)) {
    return {
      hintText: t("history.quick_report_pending"),
      pdfLabel: null,
      pdfLoading: false,
    };
  }
  return {
    hintText: null,
    pdfLabel: detail.pdfLoading
      ? t("history.generating_pdf")
      : t("history.generate_pdf"),
    pdfLoading: detail.pdfLoading,
  };
}

function buildRowViewModel(
  run: HistoryEntry,
  detail: RunDetail,
  params: PresenterParams,
): HistoryRowViewModel {
  const { expandedRunId, formatInt, fmtTs, t } = params;
  const isExpanded = expandedRunId === run.run_id;
  const rowSummary = buildHistoryRowSummary(run, detail, params);
  return {
    runId: run.run_id,
    isExpanded,
    carLabel: t("history.car_label"),
    carName: historyRowCarName(run, t),
    summaryChips: buildSummaryChips(run, detail, params),
    summaryHeadline: rowSummary.headline,
    summaryMeta: rowSummary.meta,
    toggleLabel: isExpanded
      ? t("history.close_diagnosis")
      : t("history.open_diagnosis"),
    toggleTitle: isExpanded
      ? t("history.close_diagnosis_for_run", { runId: run.run_id })
      : t("history.open_diagnosis_for_run", { runId: run.run_id }),
    startedLabel: t("history.table.updated"),
    startedAtText: fmtTs(run.start_time_utc),
    sizeLabel: t("history.table.size"),
    sampleCountText: formatInt(run.sample_count),
    quickReportLabel: t("history.quick_report"),
    collapsedAction: buildCollapsedAction(run, detail, t),
    pdfError: detail.pdfError || null,
    details: isExpanded
      ? buildHistoryDetailsViewModel(run, detail, params)
      : null,
  };
}

export function buildHistoryTableRowsViewModel(
  params: PresenterParams,
): HistoryRowViewModel[] {
  return params.runs.map((run) =>
    buildRowViewModel(
      run,
      params.runDetailsById[run.run_id] ?? EMPTY_RUN_DETAIL,
      params,
    ),
  );
}

export function buildHistoryRowsTableRenderModel(
  params: HistoryTableViewParams,
  rows: HistoryRowViewModel[],
): HistoryPanelTableRenderModel {
  return {
    kind: "rows",
    historyExportUrl: params.historyExportUrl,
    rows,
  };
}

type HistoryRowsMemoKey = Pick<
  PresenterParams,
  "expandedRunId" | "fmt" | "fmtTs" | "formatInt" | "t"
> & {
  detailState: Array<
    readonly [
      runId: string,
      preview: RunDetail["preview"],
      previewLoading: boolean,
      previewError: string,
      insights: RunDetail["insights"],
      insightsLoading: boolean,
      insightsError: string,
      pdfLoading: boolean,
      pdfError: string,
    ]
  >;
  runState: Array<
    readonly [
      runRef: HistoryEntry,
      runId: string,
      status: HistoryEntry["status"],
      errorMessage: HistoryEntry["error_message"],
      sampleCount: HistoryEntry["sample_count"],
      startTimeUtc: HistoryEntry["start_time_utc"],
      carName: HistoryEntry["car_name"],
    ]
  >;
};

function buildHistoryRowsMemoKey(params: PresenterParams): HistoryRowsMemoKey {
  return {
    expandedRunId: params.expandedRunId,
    t: params.t,
    fmt: params.fmt,
    fmtTs: params.fmtTs,
    formatInt: params.formatInt,
    runState: params.runs.map(
      (run) =>
        [
          run,
          run.run_id,
          run.status,
          run.error_message,
          run.sample_count,
          run.start_time_utc,
          run.car_name,
        ] as const,
    ),
    detailState: params.runs.map((run) => {
      const detail = params.runDetailsById[run.run_id] ?? EMPTY_RUN_DETAIL;
      return [
        run.run_id,
        detail.preview,
        detail.previewLoading,
        detail.previewError,
        detail.insights,
        detail.insightsLoading,
        detail.insightsError,
        detail.pdfLoading,
        detail.pdfError,
      ] as const;
    }),
  };
}

function shallowTupleListEqual<T extends readonly unknown[]>(
  left: T[],
  right: T[],
): boolean {
  if (left.length !== right.length) {
    return false;
  }
  for (let index = 0; index < left.length; index += 1) {
    const leftEntry = left[index];
    const rightEntry = right[index];
    if (!leftEntry || !rightEntry || leftEntry.length !== rightEntry.length) {
      return false;
    }
    for (let tupleIndex = 0; tupleIndex < leftEntry.length; tupleIndex += 1) {
      if (leftEntry[tupleIndex] !== rightEntry[tupleIndex]) {
        return false;
      }
    }
  }
  return true;
}

function sameHistoryRowsMemoKey(
  left: HistoryRowsMemoKey | null,
  right: HistoryRowsMemoKey,
): boolean {
  return (
    left !== null &&
    left.expandedRunId === right.expandedRunId &&
    left.t === right.t &&
    left.fmt === right.fmt &&
    left.fmtTs === right.fmtTs &&
    left.formatInt === right.formatInt &&
    shallowTupleListEqual(left.runState, right.runState) &&
    shallowTupleListEqual(left.detailState, right.detailState)
  );
}

export function createHistoryTableRowsMemo(): (
  params: PresenterParams,
) => HistoryRowViewModel[] {
  let previousKey: HistoryRowsMemoKey | null = null;
  let previousRows: HistoryRowViewModel[] = [];

  return (params: PresenterParams) => {
    const nextKey = buildHistoryRowsMemoKey(params);
    if (sameHistoryRowsMemoKey(previousKey, nextKey)) {
      return previousRows;
    }

    previousKey = nextKey;
    previousRows = buildHistoryTableRowsViewModel(params);
    return previousRows;
  };
}
