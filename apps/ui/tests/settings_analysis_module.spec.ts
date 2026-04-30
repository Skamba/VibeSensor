import { beforeEach, expect, test } from "vitest";
import { createSettingsAnalysisModule } from "../src/app/features/settings_analysis_module";
import { createAppState } from "../src/app/ui_app_state";
import { effect, signal } from "../src/app/ui_signals";
import type {
  AnalysisPanelActionHandlers,
  AnalysisPanelFieldKey,
  AnalysisPanelRenderModel,
  AnalysisPanelView,
} from "../src/app/views/analysis_panel";
import { installWindowGlobal } from "./async_test_helpers";
import {
  buildAnalysisSettingsHandlers,
  makeAnalysisSettingsPayload,
} from "./msw/handlers/settings";
import { createUiMswTestServer } from "./msw/node";
import { createTestQueryClient } from "./query_client_test_support";

const mswServer = createUiMswTestServer();

function lastRender(
  renders: AnalysisPanelRenderModel[],
): AnalysisPanelRenderModel {
  const render = renders.at(-1);
  if (!render) {
    throw new Error("Expected analysis panel to render");
  }
  return render;
}

function translate(key: string, vars?: Record<string, unknown>): string {
  switch (key) {
    case "settings.analysis.range_value":
      return `${vars?.min}-${vars?.max}${String(vars?.unit ?? "")}`;
    case "settings.analysis.recommended_range_label":
      return "Recommended range";
    case "settings.analysis.default_label":
      return "Default";
    case "settings.wheel_bandwidth":
      return "Wheel bandwidth";
    case "settings.analysis.invalid_number":
      return `${vars?.field ?? "Field"} must be a number`;
    case "settings.analysis.invalid_value":
      return `${vars?.field ?? "Field"} must stay between ${vars?.min ?? "?"} and ${vars?.max ?? "?"}${String(vars?.unit ?? "")}`;
    case "settings.analysis.reset_confirm":
      return "Reset analysis settings?";
    default:
      return key;
  }
}

beforeEach(() => {
  installWindowGlobal();
});

test("settings analysis module renders guidance and surfaces invalid input through the typed panel bridge", () => {
  const state = createAppState().settings;
  const renders: AnalysisPanelRenderModel[] = [];
  let actions: AnalysisPanelActionHandlers | null = null;
  let focusedField: AnalysisPanelFieldKey | null = null;
  let guidanceOpened = false;

  const panel: AnalysisPanelView = {
    actions: signal(null),
    carAvailability: signal(null),
    model: signal(null),
    focusField(field) {
      focusedField = field;
    },
    openGuidance() {
      guidanceOpened = true;
    },
  };
  effect(() => {
    actions = panel.actions.value;
  });
  effect(() => {
    const model = panel.model.value;
    if (model === null) {
      return;
    }
    renders.push(model.value);
  });

  const module = createSettingsAnalysisModule({
    panel,
    hasValidActiveCar: () => true,
    onMissingActiveCar: () => undefined,
    onSaveError: () => undefined,
    refreshSpectrumDecorations: () => undefined,
    queryClient: createTestQueryClient(),
    settings: state,
    services: {
      t: translate,
      requestConfirmation: async () => true,
      showError: () => undefined,
    },
  });

  module.bindHandlers();

  expect(lastRender(renders).fields.wheel_bandwidth_pct.guidance.lines).toEqual(
    [
      {
        label: "Recommended range",
        value: "2-12%",
      },
      {
        label: "Default",
        value: "5%",
      },
    ],
  );

  actions?.onFieldInput({
    field: "wheel_bandwidth_pct",
    value: "200",
  });
  module.saveAnalysisFromInputs();

  const invalidRender = lastRender(renders);
  expect(invalidRender.fields.wheel_bandwidth_pct.invalid).toBe(true);
  expect(invalidRender.fields.wheel_bandwidth_pct.guidance.error).toMatchObject(
    {
      body: "Wheel bandwidth must stay between 0.1 and 100%",
      compact: true,
      tone: "error",
    },
  );
  expect(focusedField).toBe("wheel_bandwidth_pct");
  expect(guidanceOpened).toBe(true);

  const rendersBeforeRecovery = renders.length;
  actions?.onFieldInput({
    field: "wheel_bandwidth_pct",
    value: "5",
  });

  expect(renders).toHaveLength(rendersBeforeRecovery + 1);
  const recoveredRender = lastRender(renders);
  expect(recoveredRender.fields.wheel_bandwidth_pct.invalid).toBe(false);
  expect(recoveredRender.fields.wheel_bandwidth_pct.guidance.error).toBeNull();
});

test("settings analysis module keeps active-car geometry when loading server analysis settings", async () => {
  const state = createAppState().settings;
  let refreshSpectrumDecorationCalls = 0;

  state.car.activeVehicleSettings.value = {
    ...state.car.activeVehicleSettings.value,
    tire_width_mm: 245,
    tire_aspect_pct: 40,
    rim_in: 19,
    final_drive_ratio: 3.23,
    current_gear_ratio: 0.72,
    tire_deflection_factor: 0.95,
  };
  state.analysis.vehicleSettings.value = {
    ...state.analysis.vehicleSettings.value,
    wheel_bandwidth_pct: 5,
    speed_uncertainty_pct: 1,
    min_abs_band_hz: 0.2,
  };

  mswServer.use(
    ...buildAnalysisSettingsHandlers({
      load: makeAnalysisSettingsPayload({
        tire_width_mm: 999,
        tire_aspect_pct: 99,
        rim_in: 24,
        final_drive_ratio: 9.99,
        current_gear_ratio: 2.22,
        tire_deflection_factor: 0.5,
        wheel_bandwidth_pct: 7.5,
        speed_uncertainty_pct: 2.5,
        min_abs_band_hz: 1.5,
      }),
    }),
  );

  const module = createSettingsAnalysisModule({
    panel: {
      actions: signal(null),
      carAvailability: signal(null),
      model: signal(null),
      focusField: () => undefined,
      openGuidance: () => undefined,
    },
    hasValidActiveCar: () => true,
    onMissingActiveCar: () => undefined,
    onSaveError: () => undefined,
    refreshSpectrumDecorations: () => {
      refreshSpectrumDecorationCalls += 1;
    },
    queryClient: createTestQueryClient(),
    settings: state,
    services: {
      t: translate,
      requestConfirmation: async () => true,
      showError: () => undefined,
    },
  });

  await module.loadAnalysisSettingsFromServer();

  expect(state.car.activeVehicleSettings.value).toMatchObject({
    tire_width_mm: 245,
    tire_aspect_pct: 40,
    rim_in: 19,
    final_drive_ratio: 3.23,
    current_gear_ratio: 0.72,
    tire_deflection_factor: 0.95,
  });
  expect(state.analysis.vehicleSettings.value).toMatchObject({
    wheel_bandwidth_pct: 7.5,
    speed_uncertainty_pct: 2.5,
    min_abs_band_hz: 1.5,
  });
  expect(refreshSpectrumDecorationCalls).toBe(1);
});

test("settings analysis module ignores loaded settings after disposal", async () => {
  const state = createAppState().settings;
  const load = createDeferred<ReturnType<typeof makeAnalysisSettingsPayload>>();
  let refreshSpectrumDecorationCalls = 0;
  mswServer.use(
    ...buildAnalysisSettingsHandlers({
      load: () => load.promise,
    }),
  );
  const module = createAnalysisModuleHarness(state, {
    refreshSpectrumDecorations: () => {
      refreshSpectrumDecorationCalls += 1;
    },
  });

  const loading = module.loadAnalysisSettingsFromServer();
  module.dispose();
  load.resolve(makeAnalysisSettingsPayload({ wheel_bandwidth_pct: 9 }));
  await loading;

  expect(state.analysis.vehicleSettings.value.wheel_bandwidth_pct).toBe(5);
  expect(refreshSpectrumDecorationCalls).toBe(0);
});

test("settings analysis module ignores saved settings after disposal", async () => {
  const state = createAppState().settings;
  const save = createDeferred<ReturnType<typeof makeAnalysisSettingsPayload>>();
  let refreshSpectrumDecorationCalls = 0;
  mswServer.use(
    ...buildAnalysisSettingsHandlers({
      save: () => save.promise,
    }),
  );
  const module = createAnalysisModuleHarness(state, {
    refreshSpectrumDecorations: () => {
      refreshSpectrumDecorationCalls += 1;
    },
  });

  const saving = module.saveAnalysisFromInputs();
  module.dispose();
  save.resolve(makeAnalysisSettingsPayload({ wheel_bandwidth_pct: 9 }));
  await saving;

  expect(state.analysis.vehicleSettings.value.wheel_bandwidth_pct).toBe(5);
  expect(refreshSpectrumDecorationCalls).toBe(0);
});

test("settings analysis module ignores repeated saves while one is in flight", async () => {
  const state = createAppState().settings;
  const save = createDeferred<ReturnType<typeof makeAnalysisSettingsPayload>>();
  let saveCalls = 0;
  let refreshSpectrumDecorationCalls = 0;
  mswServer.use(
    ...buildAnalysisSettingsHandlers({
      save: () => {
        saveCalls += 1;
        return save.promise;
      },
    }),
  );
  const module = createAnalysisModuleHarness(state, {
    refreshSpectrumDecorations: () => {
      refreshSpectrumDecorationCalls += 1;
    },
  });

  const firstSave = module.saveAnalysisFromInputs();
  const secondSave = module.saveAnalysisFromInputs();
  await flushAsyncWork();

  expect(saveCalls).toBe(1);
  save.resolve(makeAnalysisSettingsPayload({ wheel_bandwidth_pct: 9 }));
  await Promise.all([firstSave, secondSave]);

  expect(state.analysis.vehicleSettings.value.wheel_bandwidth_pct).toBe(9);
  expect(refreshSpectrumDecorationCalls).toBe(1);
});

test("settings analysis module ignores repeated reset confirmations while one is in flight", async () => {
  const state = createAppState().settings;
  const confirmation = createDeferred<boolean>();
  let confirmationCalls = 0;
  let saveCalls = 0;
  mswServer.use(
    ...buildAnalysisSettingsHandlers({
      save: () => {
        saveCalls += 1;
        return makeAnalysisSettingsPayload({ wheel_bandwidth_pct: 5 });
      },
    }),
  );
  const module = createAnalysisModuleHarness(state, {
    requestConfirmation: () => {
      confirmationCalls += 1;
      return confirmation.promise;
    },
  });
  module.bindHandlers();
  const actions = modulePanelActions(module);

  actions.onReset();
  actions.onReset();
  expect(confirmationCalls).toBe(1);

  confirmation.resolve(true);
  await flushAsyncWork();

  expect(saveCalls).toBe(1);
});

test("settings analysis module ignores reset confirmation after disposal", async () => {
  const state = createAppState().settings;
  const confirmation = createDeferred<boolean>();
  let saveCalls = 0;
  mswServer.use(
    ...buildAnalysisSettingsHandlers({
      save: () => {
        saveCalls += 1;
        return makeAnalysisSettingsPayload({ wheel_bandwidth_pct: 5 });
      },
    }),
  );
  const module = createAnalysisModuleHarness(state, {
    requestConfirmation: () => confirmation.promise,
  });
  module.bindHandlers();
  const actions = modulePanelActions(module);

  actions.onReset();
  module.dispose();
  confirmation.resolve(true);
  await flushAsyncWork();

  expect(saveCalls).toBe(0);
});

type Deferred<T> = {
  promise: Promise<T>;
  reject(reason?: unknown): void;
  resolve(value: T): void;
};

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

async function flushAsyncWork(rounds = 6): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise<void>((resolve) => {
      setImmediate(() => resolve());
    });
  }
}

type AnalysisModuleHarnessOptions = {
  refreshSpectrumDecorations?: () => void;
  requestConfirmation?: () => Promise<boolean>;
};

function createAnalysisModuleHarness(
  state: ReturnType<typeof createAppState>["settings"],
  options: AnalysisModuleHarnessOptions = {},
) {
  const panel: AnalysisPanelView = {
    actions: signal(null),
    carAvailability: signal(null),
    model: signal(null),
    focusField: () => undefined,
    openGuidance: () => undefined,
  };
  const module = createSettingsAnalysisModule({
    panel,
    hasValidActiveCar: () => true,
    onMissingActiveCar: () => undefined,
    onSaveError: () => undefined,
    refreshSpectrumDecorations:
      options.refreshSpectrumDecorations ?? (() => undefined),
    queryClient: createTestQueryClient(),
    settings: state,
    services: {
      t: translate,
      requestConfirmation: options.requestConfirmation ?? (async () => true),
      showError: () => undefined,
    },
  });
  return Object.assign(module, { __panel: panel });
}

function modulePanelActions(
  module: ReturnType<typeof createAnalysisModuleHarness>,
): AnalysisPanelActionHandlers {
  const actions = module.__panel.actions.value;
  if (!actions) {
    throw new Error("Expected analysis panel actions to be bound");
  }
  return actions;
}
