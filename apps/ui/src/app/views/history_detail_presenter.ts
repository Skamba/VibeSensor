import type { HistoryEntry, HistoryInsightsPayload } from "../../api/types";
import type { RunDetail } from "../ui_app_state";
import { buildHistoryHeatmapViewModel } from "./history_heatmap_presenter";
import {
  confidenceText,
  findingLocationText,
  findingSignatureText,
  findingSpeedBandText,
  findingTone,
  formatSourceLabel,
  historyRawCaptureState,
  historyRunDisplayTitle,
  isInconclusiveFinding,
  summarizeFindings,
  summarizeWarnings,
  type HistoryFindingPayload,
  type PresenterParams,
} from "./history_presenter_shared";
import type {
  HistoryDetailsViewModel,
  HistoryInsightsViewModel,
  HistoryPrimaryFindingViewModel,
  HistorySecondaryFindingViewModel,
  HistoryWarningBannerViewModel,
} from "./history_table_models";

function shouldShowNextStep(finding: HistoryFindingPayload | null): boolean {
  if (!finding) {
    return false;
  }
  if (isInconclusiveFinding(finding)) {
    return false;
  }
  if (findingTone(finding) === "success") {
    return true;
  }
  return (
    typeof finding.confidence === "number" &&
    Number.isFinite(finding.confidence) &&
    finding.confidence >= 0.85
  );
}

function buildPrimaryFinding(
  summary: HistoryInsightsPayload,
  params: Pick<PresenterParams, "fmt" | "t">,
): HistoryPrimaryFindingViewModel | null {
  const { t } = params;
  const findings = summarizeFindings(summary);
  const primary = findings[0];
  if (!primary) {
    return null;
  }
  const inconclusive = isInconclusiveFinding(primary);
  const location = findingLocationText(primary, summary, t);
  const signature = findingSignatureText(primary, params);
  const nextStep = inconclusive
    ? t("history.inconclusive_next_step")
    : shouldShowNextStep(primary) && location !== t("report.missing")
      ? t("history.findings_next_step", { location })
      : null;
  return {
    eyebrow: inconclusive
      ? t("history.capture_verdict")
      : t("history.primary_diagnosis"),
    headline: inconclusive
      ? t("history.inconclusive_title")
      : formatSourceLabel(primary.suspected_source, t),
    signature,
    confidence: confidenceText(primary, params),
    tone: findingTone(primary),
    explanation: String(
      primary.evidence_summary ??
        summary.most_likely_origin?.explanation ??
        (inconclusive ? t("history.inconclusive_body") : ""),
    ),
    chips: [
      { label: t("history.findings_location"), value: location },
      {
        label: t("history.findings_speed_band"),
        value: findingSpeedBandText(primary, summary, t),
      },
      { label: t("history.findings_signature"), value: signature },
    ],
    nextStepLabel: nextStep
      ? inconclusive
        ? t("history.inconclusive_next_step_label")
        : t("history.findings_next_step_label")
      : null,
    nextStep,
  };
}

function buildSecondaryFinding(
  finding: HistoryFindingPayload,
  summary: HistoryInsightsPayload,
  params: Pick<PresenterParams, "fmt" | "t">,
): HistorySecondaryFindingViewModel {
  const { t } = params;
  return {
    source: formatSourceLabel(finding.suspected_source, t),
    confidence: confidenceText(finding, params),
    tone: findingTone(finding),
    signature: findingSignatureText(finding, params),
    locationLabel: t("history.findings_location"),
    location: findingLocationText(finding, summary, t),
    speedBandLabel: t("history.findings_speed_band"),
    speedBand: findingSpeedBandText(finding, summary, t),
    evidenceSummary: String(finding.evidence_summary ?? ""),
  };
}

function buildHistoryInsightsViewModel(
  detail: RunDetail,
  params: Pick<PresenterParams, "fmt" | "t">,
): HistoryInsightsViewModel {
  const { t } = params;
  const loadedInsights = detail.insights ?? detail.preview;
  const loading =
    detail.insightsLoading ||
    (detail.previewLoading && loadedInsights === null);
  if (loadedInsights === null) {
    return {
      headerEyebrow: t("history.findings_title"),
      stateMessage: loading
        ? t("history.loading_insights")
        : t("history.findings_pending"),
      primary: null,
      secondaryTitle: null,
      visibleSecondary: [],
      hiddenSecondary: [],
      showMoreLabel: null,
      emptyMessage: null,
    };
  }
  const findings = summarizeFindings(loadedInsights);
  if (!findings.length) {
    return {
      headerEyebrow: t("history.findings_title"),
      stateMessage: null,
      primary: null,
      secondaryTitle: null,
      visibleSecondary: [],
      hiddenSecondary: [],
      showMoreLabel: null,
      emptyMessage: t("report.no_findings_for_run"),
    };
  }
  const secondaryFindings = findings.slice(1);
  const hiddenSecondary = secondaryFindings
    .slice(2)
    .map((finding) => buildSecondaryFinding(finding, loadedInsights, params));
  return {
    headerEyebrow: t("history.findings_title"),
    stateMessage: null,
    primary: buildPrimaryFinding(loadedInsights, params),
    secondaryTitle: secondaryFindings.length
      ? t("history.secondary_candidates_title")
      : null,
    visibleSecondary: secondaryFindings
      .slice(0, 2)
      .map((finding) => buildSecondaryFinding(finding, loadedInsights, params)),
    hiddenSecondary,
    showMoreLabel: hiddenSecondary.length
      ? t("history.show_more_findings", { count: hiddenSecondary.length })
      : null,
    emptyMessage: null,
  };
}

function buildHistoryWarnings(
  detail: RunDetail,
): HistoryWarningBannerViewModel[] {
  const warnings = summarizeWarnings(detail.preview).concat(
    summarizeWarnings(detail.insights),
  );
  return warnings
    .filter(
      (warning, index) =>
        warnings.findIndex((candidate) => candidate.code === warning.code) ===
        index,
    )
    .map((warning) => ({
      severity: String(warning.severity),
      title: String(warning.title),
      detail: warning.detail ? String(warning.detail) : null,
    }));
}

function buildArtifactWarnings(
  run: HistoryEntry,
  t: PresenterParams["t"],
): HistoryWarningBannerViewModel[] {
  const rawCaptureState = historyRawCaptureState(run);
  if (rawCaptureState === "missing") {
    return [
      {
        severity: "warn",
        title: t("history.raw_capture_missing_title"),
        detail: t("history.raw_capture_missing_detail"),
      },
    ];
  }
  if (rawCaptureState !== "degraded" || run.raw_capture_finalize == null) {
    return [];
  }
  let detailKey: string | null = null;
  switch (run.raw_capture_finalize.status) {
    case "enqueue_timeout":
      detailKey = "history.raw_capture_degraded_enqueue_timeout_detail";
      break;
    case "timeout":
      detailKey = "history.raw_capture_degraded_timeout_detail";
      break;
    case "failed":
      detailKey = "history.raw_capture_degraded_failed_detail";
      break;
    default:
      return [];
  }
  return [
    {
      severity: "warn",
      title: t("history.raw_capture_degraded_title"),
      detail: t(detailKey, {
        queueDepth: run.raw_capture_finalize.queue_depth ?? "unknown",
        errorSummary:
          run.raw_capture_finalize.error_summary ?? t("history.not_reported"),
      }),
    },
  ];
}

export function buildHistoryDetailsViewModel(
  run: HistoryEntry,
  detail: RunDetail,
  params: Pick<PresenterParams, "fmt" | "fmtTs" | "formatInt" | "t">,
): HistoryDetailsViewModel {
  const { fmt, fmtTs, formatInt, t } = params;
  const summary = detail.insights ?? detail.preview;
  const hasDiagnosis = Boolean(detail.insights || detail.preview);
  const showReloadAction = hasDiagnosis || Boolean(detail.insightsError);
  const showLoadingStatus =
    detail.insightsLoading || (detail.previewLoading && !hasDiagnosis);
  const runSummary = summary
    ? [
        `${t("report.run_id")}: ${run.run_id}`,
        `${t("history.summary_created")}: ${fmtTs(summary.start_time_utc as string)}`,
        `${t("history.summary_updated")}: ${fmtTs(run.end_time_utc ?? "")}`,
        `${t("history.summary_size")}: ${fmt(summary.duration_s as number, 1)} s`,
        `${t("history.summary_sensor_count")}: ${formatInt(summary.sensor_count_used as number)}`,
      ].join(" · ")
    : null;
  const heatmap = detail.previewLoading
    ? buildHistoryHeatmapViewModel(null, params, {
        stateMessage: t("history.loading_preview"),
        stateTone: "subtle",
      })
    : detail.previewError
      ? buildHistoryHeatmapViewModel(null, params, {
          stateMessage: detail.previewError,
          stateTone: "error",
        })
      : summary
        ? buildHistoryHeatmapViewModel(summary, params)
        : buildHistoryHeatmapViewModel(null, params, {
            stateMessage: t("history.preview_unavailable"),
            stateTone: "subtle",
          });
  return {
    titleEyebrow: t("history.details_title"),
    title: historyRunDisplayTitle(run, t),
    runSummary,
    reloadActionLabel: showReloadAction
      ? detail.insightsLoading
        ? t("history.loading_insights")
        : hasDiagnosis
          ? t("history.reload_insights")
          : t("history.load_insights")
      : null,
    reloadActionDisabled: detail.insightsLoading,
    loadingStatusText: showReloadAction
      ? null
      : showLoadingStatus
        ? t("history.loading_insights")
        : null,
    insightsError: detail.insightsError || null,
    warnings: buildArtifactWarnings(run, t).concat(
      buildHistoryWarnings(detail),
    ),
    insights: buildHistoryInsightsViewModel(detail, params),
    heatmap,
    footerEyebrow: t("history.run_actions_title"),
    footerBody: t("history.run_actions_body"),
    exportLabel: t("history.export"),
    deleteLabel: t("history.delete"),
  };
}
