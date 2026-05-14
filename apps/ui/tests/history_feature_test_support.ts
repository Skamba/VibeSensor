import { afterEach, beforeEach, expect } from "vitest";
import { createHistoryFeature } from "../src/app/features/history_feature";
import { createAppState, type RunDetail } from "../src/app/ui_app_state";
import { effect, signal } from "../src/app/ui_signals";
import type {
  HistoryPanelActionHandlers,
  HistoryPanelRenderModel,
  HistoryPanelView,
} from "../src/app/views/history_table_view";
import { installWindowGlobal } from "./async_test_helpers";
import {
  makeHistoryFinding,
  makeHistoryInsightsPayload,
  makeLocationIntensityRow,
} from "./history_payload_test_support";
import { createUiMswTestServer } from "./msw/node";
import { createTestQueryClient } from "./query_client_test_support";

export const mswServer = createUiMswTestServer();

const activeHarnessCleanups: Array<() => Promise<void>> = [];

type ButtonStub = HTMLButtonElement & {
  disabled: boolean;
};

type TextStub = {
  textContent: string;
};

function createButton(): ButtonStub {
  return {
    disabled: false,
    addEventListener() {
      /* no-op */
    },
  } as unknown as ButtonStub;
}

function createTextElement(): TextStub {
  return { textContent: "" };
}

function createHistoryElements(): {
  panel: HistoryPanelView;
  historySummary: TextStub;
  deleteAllRunsBtn: ButtonStub;
  getLatestHandlers(): HistoryPanelActionHandlers | null;
  getLatestModel(): HistoryPanelRenderModel | null;
  getRenderCount(): number;
} {
  const historySummary = createTextElement();
  const deleteAllRunsBtn = createButton();
  let latestModel: HistoryPanelRenderModel | null = null;
  let latestHandlers: HistoryPanelActionHandlers | null = null;
  let renderCount = 0;
  const panel: HistoryPanelView = {
    actions: signal(null),
    model: signal(null),
  };
  effect(() => {
    latestHandlers = panel.actions.value;
  });
  effect(() => {
    const model = panel.model.value;
    if (model === null) {
      return;
    }
    const nextModel = model.value;
    renderCount += 1;
    latestModel = nextModel;
    historySummary.textContent = nextModel.historySummaryText;
    deleteAllRunsBtn.disabled = nextModel.deleteAllRunsDisabled;
  });
  return {
    panel,
    historySummary,
    deleteAllRunsBtn,
    getLatestHandlers() {
      return latestHandlers;
    },
    getLatestModel() {
      return latestModel;
    },
    getRenderCount() {
      return renderCount;
    },
  };
}

export function historyInsightsPayload(runId: string, sensorCountUsed: number) {
  return makeHistoryInsightsPayload({
    run_id: runId,
    start_time_utc: "2026-01-01T00:00:00Z",
    duration_s: 12.3,
    sensor_count_used: sensorCountUsed,
  });
}

export function historyInsightsWithFindingsPayload(
  runId: string,
  sensorCountUsed: number,
) {
  return {
    ...historyInsightsPayload(runId, sensorCountUsed),
    most_likely_origin: {
      suspected_source: "Front-right wheel imbalance",
      location: "Front-right wheel",
      speed_band: "60-90 km/h",
      explanation:
        "Order content and spatial dominance agree on the front-right wheel.",
    },
    findings: [
      makeHistoryFinding({
        finding_id: "finding-1",
        confidence: 0.92,
        confidence_pct: "92%",
        confidence_tone: "success",
        evidence_summary:
          "Consistent wheel-order energy remains strongest at the front-right wheel.",
        frequency_hz_or_order: "1x wheel",
        strongest_location: "Front-right wheel",
        strongest_speed_band: "60-90 km/h",
        suspected_source: "Front-right wheel imbalance",
      }),
      makeHistoryFinding({
        finding_id: "finding-2",
        confidence: 0.67,
        confidence_pct: "67%",
        confidence_tone: "warn",
        evidence_summary:
          "Secondary driveline energy appears at the tunnel but is weaker than the wheel finding.",
        frequency_hz_or_order: "1x driveshaft",
        strongest_location: "Driveshaft tunnel",
        strongest_speed_band: "70-90 km/h",
        suspected_source: "Secondary driveline contribution",
      }),
    ],
    sensor_intensity_by_location: [
      makeLocationIntensityRow({
        location: "Front Right Wheel",
        p50_intensity_db: 18,
        p95_intensity_db: 32,
        max_intensity_db: 40,
      }),
    ],
  };
}

export function historyInsightsAnalyzingPayload(runId: string) {
  return {
    run_id: runId,
    status: "analyzing" as const,
  };
}

export function historyListRun(
  runId: string,
  overrides: Partial<{
    car_name: string;
    error_message: string | null;
    sample_count: number;
    start_time_utc: string;
    status: "complete" | "analyzing" | "error";
  }> = {},
) {
  return {
    run_id: runId,
    status: overrides.status ?? "complete",
    start_time_utc: overrides.start_time_utc ?? "2026-01-01T00:00:00Z",
    end_time_utc: "2026-01-01T00:00:12Z",
    created_at: "2026-01-01T00:00:00Z",
    sample_count: overrides.sample_count ?? 42,
    car_name: overrides.car_name ?? "Track Car",
    error_message: overrides.error_message ?? null,
  };
}

function testTranslation(key: string, vars?: Record<string, unknown>): string {
  return vars ? `${key}:${JSON.stringify(vars)}` : key;
}

export function ensureRunDetail(
  state: ReturnType<typeof createAppState>,
  runId: string,
): RunDetail {
  if (!state.history.runDetailsById.value[runId]) {
    state.history.runDetailsById.value = {
      ...state.history.runDetailsById.value,
      [runId]: {
        preview: null,
        previewLoading: false,
        previewError: "",
        insights: null,
        insightsLoading: false,
        insightsError: "",
        pdfLoading: false,
        pdfError: "",
      },
    };
  }
  return state.history.runDetailsById.value[runId];
}

export function latestRowModels(panel: {
  getLatestModel(): HistoryPanelRenderModel | null;
}) {
  const model = panel.getLatestModel();
  expect(model?.table?.kind).toBe("rows");
  if (!model?.table || model.table.kind !== "rows") {
    throw new Error("Expected rendered history rows");
  }
  return model.table.rows;
}

export function createFeatureHarness(
  state = createAppState(),
  overrides: {
    panel?: HistoryPanelView;
    showError?: (message: string) => void;
    requestConfirmation?: (message: string) => Promise<boolean>;
    activatePrimaryView?: (viewId: string) => void;
  } = {},
) {
  const panelElements = createHistoryElements();
  const errors: string[] = [];
  const primaryViewActivations: string[] = [];
  const queryClient = createTestQueryClient();
  const feature = createHistoryFeature({
    panel: overrides.panel ?? panelElements.panel,
    navigation: {
      activatePrimaryView(viewId: string) {
        if (overrides.activatePrimaryView) {
          overrides.activatePrimaryView(viewId);
          return;
        }
        primaryViewActivations.push(viewId);
      },
    },
    history: state.history,
    queryClient,
    shell: state.shell,
    services: {
      t: testTranslation,
      requestConfirmation: overrides.requestConfirmation ?? (async () => true),
      showError:
        overrides.showError ??
        ((message) => {
          errors.push(message);
        }),
    },
    formatting: {
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      fmtTs: (iso) => iso,
      formatInt: (value) => String(value),
    },
  });
  activeHarnessCleanups.push(async () => {
    feature.dispose();
    await queryClient.cancelQueries();
    queryClient.clear();
  });
  return {
    feature,
    state,
    errors,
    primaryViewActivations,
    ...panelElements,
  };
}

export function installHistoryFeatureTestLifecycle(): void {
  beforeEach(() => {
    installWindowGlobal();
  });

  afterEach(async () => {
    while (activeHarnessCleanups.length > 0) {
      await activeHarnessCleanups.pop()?.();
    }
  });
}
