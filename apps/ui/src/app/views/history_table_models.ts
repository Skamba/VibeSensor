export type HistorySummaryChipTone = "ok" | "warn" | "bad" | "muted" | "source" | "default";
export type HistoryFindingTone = "success" | "warn" | "neutral";

export interface HistorySummaryChipViewModel {
  key: string;
  text: string;
  tone: HistorySummaryChipTone;
}

export interface HistoryCollapsedActionViewModel {
  hintText: string | null;
  pdfLabel: string | null;
  pdfLoading: boolean;
}

export interface HistoryFindingMetaViewModel {
  label: string;
  value: string;
}

export interface HistoryPrimaryFindingViewModel {
  eyebrow: string;
  headline: string;
  signature: string;
  confidence: string;
  tone: HistoryFindingTone;
  explanation: string;
  chips: HistoryFindingMetaViewModel[];
  nextStepLabel: string | null;
  nextStep: string | null;
}

export interface HistorySecondaryFindingViewModel {
  source: string;
  confidence: string;
  tone: HistoryFindingTone;
  signature: string;
  locationLabel: string;
  location: string;
  speedBandLabel: string;
  speedBand: string;
  evidenceSummary: string;
}

export interface HistoryWarningBannerViewModel {
  severity: string;
  title: string;
  detail: string | null;
}

export interface HistoryHeatmapZoneViewModel {
  key: string;
  label: string;
  gridArea: string;
  valueLabel: string | null;
  strongest: boolean;
  accentColor: string | null;
  fillPercent: number | null;
}

export interface HistoryHeatmapViewModel {
  title: string;
  stateMessage: string | null;
  stateTone: "subtle" | "error" | null;
  zones: HistoryHeatmapZoneViewModel[];
  extras: string[];
}

export interface HistoryInsightsViewModel {
  headerEyebrow: string;
  stateMessage: string | null;
  primary: HistoryPrimaryFindingViewModel | null;
  secondaryTitle: string | null;
  visibleSecondary: HistorySecondaryFindingViewModel[];
  hiddenSecondary: HistorySecondaryFindingViewModel[];
  showMoreLabel: string | null;
  emptyMessage: string | null;
}

export interface HistoryDetailsViewModel {
  titleEyebrow: string;
  title: string;
  runSummary: string | null;
  reloadActionLabel: string | null;
  reloadActionDisabled: boolean;
  loadingStatusText: string | null;
  insightsError: string | null;
  warnings: HistoryWarningBannerViewModel[];
  insights: HistoryInsightsViewModel;
  heatmap: HistoryHeatmapViewModel;
  footerEyebrow: string;
  footerBody: string;
  exportLabel: string;
  deleteLabel: string;
}

export interface HistoryRowViewModel {
  runId: string;
  isExpanded: boolean;
  carLabel: string;
  carName: string;
  summaryChips: HistorySummaryChipViewModel[];
  summaryHeadline: string | null;
  summaryMeta: string | null;
  toggleLabel: string;
  toggleTitle: string;
  startedLabel: string;
  startedAtText: string;
  sizeLabel: string;
  sampleCountText: string;
  quickReportLabel: string;
  collapsedAction: HistoryCollapsedActionViewModel;
  pdfError: string | null;
  details: HistoryDetailsViewModel | null;
}
