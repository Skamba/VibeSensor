import { batch, computed, effect, signal, untracked } from "@preact/signals";

import { activeView } from "../../app_store";
import { t } from "../../i18n";
import {
  clients,
  hasReceivedPayload,
  payloadError,
  rotationalSpeeds,
  spectra,
  speedMps,
  wsState,
} from "../../live_store";
import {
  activeCar,
  carSelection,
  speedSettings,
  speedStatus,
} from "../../settings_store";
import { gpsReceiverMissing } from "../../speed_source";
import {
  createSpectrumFramePreparer,
  type SpectrumPreparedFrameData,
} from "./frame_preparer";
import {
  activeFrequency,
  bandStatus,
  bandsAt,
  createInspectorFeed,
  type FocusMarker,
  focusEntry,
  focusPeak,
  inspectorText,
  legendModel,
  orderBands,
  overlayMessage,
  type SensorLevels,
} from "./spectrum_model";
import {
  createSpectrumRenderer,
  type SpectrumRenderer,
} from "./spectrum_renderer";

const EMPTY_FRAME: SpectrumPreparedFrameData = {
  entries: [],
  freqAxis: [],
  frame: null,
  hasData: false,
};

const prepared = signal<SpectrumPreparedFrameData>(EMPTY_FRAME);
const pinnedId = signal<string | null>(null);
const cursorIdx = signal<number | null>(null);
const bandsRequested = signal(false);
const chartLoading = signal(false);
const chartLoadError = signal<string | null>(null);
const prepareError = signal<string | null>(null);
export const inspector = signal("");

const levels: SensorLevels = {
  strengthDb: (id) =>
    spectra.value.clients[id]?.strength_metrics?.vibration_strength_db ?? null,
  topPeakHz: (id) =>
    spectra.value.clients[id]?.strength_metrics?.top_peaks?.[0]?.hz ?? null,
};

const chartBands = computed(() =>
  orderBands(rotationalSpeeds.value, activeCar.value?.fuel_type ?? null, t),
);
export const hasBands = computed(
  () => chartBands.value.length > 0 && prepared.value.entries.length > 0,
);
/** Which order families can be drawn, or why none are. */
export const bandCoverage = computed(() => {
  const selection = carSelection.value.kind;
  return bandStatus(
    {
      carActive: selection !== "no_cars" && selection !== "no_active_car",
      fuelType: activeCar.value?.fuel_type ?? null,
      speeds: rotationalSpeeds.value,
      speedMps: speedMps.value,
      gpsReceiverMissing: gpsReceiverMissing(
        speedSettings.source.value,
        speedStatus.value,
      ),
    },
    t,
  );
});
export const bandsVisible = computed(
  () => bandsRequested.value && hasBands.value,
);
effect(() => {
  if (!hasBands.value) {
    bandsRequested.value = false;
  }
});

const inspectorInput = computed(() => ({
  entries: prepared.value.entries,
  freqAxis: prepared.value.freqAxis,
  bands: chartBands.value,
  pinnedId: pinnedId.value,
  cursorIdx: cursorIdx.value,
  levels,
}));

export const legend = computed(() =>
  legendModel(prepared.value.entries, pinnedId.value, levels, t),
);

/** Reference bands at the inspected frequency. */
export const activeBands = computed(() => {
  const freq = activeFrequency(inspectorInput.value);
  return freq === null ? [] : bandsAt(chartBands.value, freq);
});

export const overlay = computed(() =>
  overlayMessage(
    {
      chartLoadError: chartLoadError.value,
      prepareError: prepareError.value,
      payloadError: payloadError.value,
      hasReceivedPayload: hasReceivedPayload.value,
      wsState: wsState.value,
      chartLoading: chartLoading.value,
      hasData: prepared.value.hasData,
    },
    t,
  ),
);

export function toggleBands(): void {
  bandsRequested.value = hasBands.value && !bandsRequested.value;
}

export function selectTrace(id: string): void {
  pinnedId.value = pinnedId.value === id ? null : id;
}

export function showAllTraces(): void {
  pinnedId.value = null;
}

function focusMarker(): FocusMarker | null {
  const { entries, freqAxis } = prepared.peek();
  const entry = focusEntry(entries, pinnedId.peek(), levels);
  const peak = entry ? focusPeak(entry, freqAxis, levels) : null;
  return entry && peak ? { color: entry.color, ...peak } : null;
}

function errorDetail(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return typeof error === "string" && error.trim() ? error : "Unknown error";
}

/** Creates the chart in the given elements and keeps it in sync until disposed. */
export function mountSpectrum(dom: {
  specChart: HTMLElement;
  specChartWrap: HTMLElement;
}): () => void {
  const preparer = createSpectrumFramePreparer();
  const applyIsolation = () => {
    const id = pinnedId.peek();
    const index = id
      ? prepared.peek().entries.findIndex((entry) => entry.id === id)
      : -1;
    renderer.setSeriesIsolation(index >= 0 ? index + 1 : null);
  };
  const renderer: SpectrumRenderer = createSpectrumRenderer({
    dom,
    t,
    canTween: () => wsState.peek() === "connected",
    chartLoading,
    chartLoadError,
    getBandsVisible: () => bandsVisible.peek(),
    getChartBands: () => chartBands.peek(),
    getFocusMarker: focusMarker,
    onCursorDataIndexChange: (index) => {
      cursorIdx.value = index;
    },
    onAsyncChartUpdate: applyIsolation,
  });
  const renderFrame = () => {
    let next: SpectrumPreparedFrameData;
    try {
      next = preparer.prepare({
        clients: clients.peek(),
        spectraByClient: spectra.peek().clients,
      });
    } catch (error) {
      prepareError.value = errorDetail(error);
      return;
    }
    batch(() => {
      prepareError.value = null;
      prepared.value = next;
      const id = pinnedId.peek();
      if (id && !next.entries.some((entry) => entry.id === id)) {
        pinnedId.value = null;
      }
    });
    renderer.render(next);
    applyIsolation();
  };
  const feed = createInspectorFeed({
    show: (text) => {
      inspector.value = text;
    },
    now: () => performance.now(),
    schedule: (run, delayMs) => {
      const timer = setTimeout(run, delayMs);
      return () => clearTimeout(timer);
    },
  });
  const stops = [
    effect(() => {
      void spectra.value;
      untracked(renderFrame);
    }),
    effect(() => {
      void pinnedId.value;
      untracked(applyIsolation);
    }),
    effect(() => {
      void bandsVisible.value;
      void chartBands.value;
      untracked(() => renderer.refreshDecorations());
    }),
    effect(() => {
      if (activeView.value === "dashboardView") {
        untracked(() => renderer.resize());
      }
    }),
    effect(() => {
      const line = inspectorText(inspectorInput.value, t);
      untracked(() => feed.update(line));
    }),
  ];
  return () => {
    for (const stop of stops) {
      stop();
    }
    feed.dispose();
    preparer.dispose();
    renderer.dispose();
  };
}
