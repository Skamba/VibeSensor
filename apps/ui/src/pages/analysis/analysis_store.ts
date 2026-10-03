import { batch, computed, effect, signal } from "@preact/signals";

import { getAnalysisSettings, setAnalysisSettings } from "../../api/settings";
import type {
  AnalysisSettingsPayload,
  AnalysisSettingsRequest,
} from "../../api/types";
import {
  errorMessage,
  onViewEnter,
  requestConfirmation,
  showError,
} from "../../app_store";
import type { Feedback } from "../../components/feedback";
import { lang, t } from "../../i18n";
import { activeCar, analysisTuning, carSelection } from "../../settings_store";
import {
  defaultAnalysisTuningSettings,
  mergeAnalysisTuningSettings,
} from "../../vehicle_settings";
import {
  checkDrafts,
  type Drafts,
  draftsFrom,
  type FieldKey,
} from "./analysis_model";

export const drafts = signal<Drafts>(draftsFrom(analysisTuning.value));
export const fieldErrors = signal<Partial<Record<FieldKey, string>>>({});
export const saveFeedback = signal<Feedback | null>(null);
/** Bumped to open the guidance disclosure. */
export const guidanceRequest = signal(0);
export const focusRequest = signal<{ field: FieldKey; seq: number } | null>(
  null,
);
export const hasActiveCar = computed(
  () => carSelection.value.kind === "active",
);
export const carsLoading = computed(
  () => carSelection.value.kind === "loading",
);

function resetDrafts(): void {
  batch(() => {
    drafts.value = draftsFrom(analysisTuning.peek());
    fieldErrors.value = {};
    saveFeedback.value = null;
  });
}

const activeCarId = computed(() => activeCar.value?.id ?? null);

// Switching car or language starts from the saved values again.
effect(() => {
  activeCarId.value;
  lang.value;
  resetDrafts();
});

function apply(payload: AnalysisSettingsPayload): void {
  analysisTuning.value = mergeAnalysisTuningSettings(
    analysisTuning.peek(),
    payload,
  );
  resetDrafts();
}

let loaded = false;
onViewEnter("settingsView", async () => {
  if (!loaded) {
    apply(await getAnalysisSettings());
    loaded = true;
  }
});

export function editField(field: FieldKey, value: string): void {
  batch(() => {
    drafts.value = { ...drafts.value, [field]: value };
    const { [field]: _cleared, ...others } = fieldErrors.value;
    fieldErrors.value = others;
    saveFeedback.value = null;
  });
}

let mutationInFlight = false;

async function persist(request: AnalysisSettingsRequest): Promise<void> {
  try {
    apply(await setAnalysisSettings(request));
  } catch (error) {
    const message = errorMessage(error, t("settings.save_failed"));
    batch(() => {
      guidanceRequest.value += 1;
      saveFeedback.value = {
        tone: "error",
        title: t("settings.analysis.save_failed_title"),
        body: message,
        detail: t("settings.analysis.save_failed_detail"),
      };
    });
    showError(message);
  }
}

export async function saveAnalysis(): Promise<void> {
  if (mutationInFlight || !hasActiveCar.value) {
    return;
  }
  batch(() => {
    fieldErrors.value = {};
    saveFeedback.value = null;
  });
  const check = checkDrafts(drafts.value, t);
  if (check.kind === "invalid") {
    batch(() => {
      fieldErrors.value = { [check.field]: check.message };
      focusRequest.value = {
        field: check.field,
        seq: (focusRequest.peek()?.seq ?? 0) + 1,
      };
      guidanceRequest.value += 1;
    });
    return;
  }
  mutationInFlight = true;
  try {
    if (
      check.kind === "risky" &&
      !(await requestConfirmation(check.confirmation))
    ) {
      return;
    }
    await persist(check.request);
  } finally {
    mutationInFlight = false;
  }
}

export async function resetAnalysis(): Promise<void> {
  if (mutationInFlight || !hasActiveCar.value) {
    return;
  }
  mutationInFlight = true;
  try {
    if (!(await requestConfirmation(t("settings.analysis.reset_confirm")))) {
      return;
    }
    batch(() => {
      fieldErrors.value = {};
      saveFeedback.value = null;
    });
    await persist({ ...defaultAnalysisTuningSettings });
  } finally {
    mutationInFlight = false;
  }
}
