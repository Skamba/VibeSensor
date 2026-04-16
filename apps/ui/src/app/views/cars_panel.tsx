import { render } from "preact";

import { useEffect, useRef } from "preact/hooks";
import type {
  CarsFeatureFocusTarget,
  CarsFeatureManualInputState,
} from "../features/cars_feature_workflow";
import { useUiTranslation } from "../ui_i18n";
import {
  signal,
  useSignal,
  type ReadonlySignal,
} from "../ui_signals";
import {
  createClosedCarsWizardRenderModel,
  type CarsWizardOptionItem,
  type CarsWizardOptionsRenderModel,
  type CarsWizardRenderModel,
} from "./car_wizard_view";
import {
  inlineStateActionClass,
} from "./dom_helpers";
import {
  type CarsInlineStateViewModel,
  type CarsListAction,
  type CarsListRowViewModel,
  type SettingsCarListTableRenderModel,
} from "./settings_car_list_view";

export interface CarsListRenderModel {
  guidance: CarsInlineStateViewModel | null;
  table: SettingsCarListTableRenderModel | null;
}

export interface CarsListPanelView {
  bindActions(handlers: { onAction(action: CarsListAction): void }): void;
  bindModel(model: ReadonlySignal<CarsListRenderModel>): void;
}

export type CarsFeatureInteraction =
  | { type: "back" }
  | { type: "close" }
  | { type: "finish" }
  | { type: "manual-inputs-changed"; inputs: CarsFeatureManualInputState }
  | { type: "open" }
  | { type: "select-brand"; value: string }
  | { type: "select-gearbox"; index: number }
  | { type: "select-model"; index: number }
  | { type: "select-tire"; index: number }
  | { type: "select-type"; value: string }
  | { type: "select-variant"; index: number }
  | { type: "submit-custom-brand"; value: string }
  | { type: "submit-custom-model"; value: string }
  | { type: "submit-custom-type"; value: string };

export interface CarsFeatureInteractionHandlers {
  onAction(action: CarsFeatureInteraction): void;
}

export interface CarsWizardPanelBridge {
  bindActions(handlers: CarsFeatureInteractionHandlers): void;
  focus(target: CarsFeatureFocusTarget): void;
  bindModel(model: ReadonlySignal<CarsWizardRenderModel>): void;
}

export interface CarsPanelView {
  readonly list: CarsListPanelView;
  readonly wizard: CarsWizardPanelBridge;
}

type CarsListPanelActionHandlers = {
  onAction(action: CarsListAction): void;
};

type CarsWizardOptionRefs = {
  brandOption: HTMLButtonElement | null;
  gearboxOption: HTMLButtonElement | null;
  modelOption: HTMLButtonElement | null;
  tireOption: HTMLButtonElement | null;
  typeOption: HTMLButtonElement | null;
  variantOption: HTMLButtonElement | null;
};

type CarsPanelBridgeState = {
  actions: CarsListPanelActionHandlers | null;
  model: ReadonlySignal<CarsListRenderModel> | null;
  wizardActions: CarsFeatureInteractionHandlers | null;
  wizardModel: ReadonlySignal<CarsWizardRenderModel> | null;
};

type CarsWizardFocusRequest = {
  target: CarsFeatureFocusTarget;
  token: number;
};

const DEFAULT_CARS_PANEL_MODEL: CarsListRenderModel = {
  guidance: null,
  table: null,
};

const WIZARD_STEP_LABELS = [
  { key: "settings.car.step_brand_short", fallback: "Brand" },
  { key: "settings.car.step_type_short", fallback: "Type" },
  { key: "settings.car.step_model_short", fallback: "Model" },
  { key: "settings.car.step_variant_short", fallback: "Variant" },
  { key: "settings.car.step_specs_short", fallback: "Specs" },
] as const;

function handleCarsListAction(
  actions: CarsListPanelActionHandlers | null,
  action: CarsListAction,
): void {
  actions?.onAction(action);
}

function focusElement(target: HTMLElement | null | undefined): void {
  target?.focus();
}

function parseWizardOptionIndex(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}

type CarsWizardFocusRefs = {
  closeButton: HTMLButtonElement | null;
  customBrandInput: HTMLInputElement | null;
  customModelInput: HTMLInputElement | null;
  customTypeInput: HTMLInputElement | null;
  finalDriveInput: HTMLInputElement | null;
  manualAddButton: HTMLButtonElement | null;
  optionRefs: CarsWizardOptionRefs;
  rimInput: HTMLInputElement | null;
  tireAspectInput: HTMLInputElement | null;
  tireWidthInput: HTMLInputElement | null;
  topGearInput: HTMLInputElement | null;
};

function resolveWizardFocusTarget(
  target: CarsFeatureFocusTarget,
  refs: CarsWizardFocusRefs,
): HTMLElement | null {
  switch (target) {
    case "brand-option":
      return refs.optionRefs.brandOption ?? refs.customBrandInput;
    case "close":
      return refs.closeButton;
    case "custom-brand":
      return refs.customBrandInput;
    case "custom-model":
      return refs.customModelInput;
    case "custom-type":
      return refs.customTypeInput;
    case "finish":
      return refs.manualAddButton;
    case "gearbox-option":
      return refs.optionRefs.gearboxOption ?? refs.manualAddButton;
    case "manual-final-drive":
      return refs.finalDriveInput;
    case "manual-rim":
      return refs.rimInput;
    case "manual-tire-aspect":
      return refs.tireAspectInput;
    case "manual-tire-width":
      return refs.tireWidthInput;
    case "manual-top-gear":
      return refs.topGearInput;
    case "model-option":
      return refs.optionRefs.modelOption ?? refs.customModelInput;
    case "spec-selection":
      return refs.optionRefs.tireOption ?? refs.optionRefs.gearboxOption ?? refs.tireWidthInput;
    case "type-option":
      return refs.optionRefs.typeOption ?? refs.customTypeInput;
    case "variant-option":
      return refs.optionRefs.variantOption;
  }
}

function CarsInlineStatePanel(props: {
  actions: CarsListPanelActionHandlers | null;
  state: CarsInlineStateViewModel;
}) {
  const { actions, state } = props;
  const rootClass = state.tone === "success"
    ? "empty-state empty-state--inline car-selection-feedback car-selection-feedback--success"
    : "empty-state empty-state--inline empty-state--actionable";
  return (
    <div class={rootClass} role={state.tone === "success" ? "status" : undefined}>
      <strong class="empty-state__title">{state.titleText}</strong>
      <span class="empty-state__body">{state.bodyText}</span>
      {state.detailText ? (
        <span class="empty-state__detail">{state.detailText}</span>
      ) : null}
      {state.action ? (
        <div class="empty-state__actions">
          <button
            type="button"
            class={inlineStateActionClass(state.action.variant)}
            data-inline-state-action={state.action.type === "add" ? "add-car" : state.action.type}
            onClick={() =>
              handleCarsListAction(actions, {
                type: state.action?.type ?? "add",
                carId: null,
              })}
          >
            {state.action.labelText}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function CarsTableRow(props: {
  actions: CarsListPanelActionHandlers | null;
  row: CarsListRowViewModel;
}) {
  const { actions, row } = props;
  const primaryAction = row.primaryAction;
  return (
    <tr
      class={row.isHighlighted ? "car-list-row--highlighted" : undefined}
      data-car-id={row.carId}
      data-car-complete={row.isComplete ? "true" : "false"}
      data-highlighted={row.isHighlighted ? "true" : "false"}
    >
      <td>
        <div class="car-row__identity">
          <div class="car-row__heading">
            <strong>{row.displayName}</strong>
          </div>
          {row.metaTypeText || row.metaVariantText ? (
            <div class="car-row__meta">
              {row.metaTypeText ? <span class="car-row__type">{row.metaTypeText}</span> : null}
              {row.metaVariantText ? (
                <span class="car-row__variant">{row.metaVariantText}</span>
              ) : null}
            </div>
          ) : null}
          <div class="car-status-stack">
            <span
              class="car-active-pill settings-entity-status"
              data-state={row.activeState}
            >
              {row.activeStatusText}
            </span>
            <span
              class="car-readiness-pill settings-entity-status"
              data-state={row.readinessState}
            >
              {row.readinessStatusText}
            </span>
            {row.highlightedStatusText ? (
              <span class="car-created-pill settings-entity-status">
                {row.highlightedStatusText}
              </span>
            ) : null}
          </div>
          {row.completionDetailText ? (
            <span class="subtle car-row__detail">{row.completionDetailText}</span>
          ) : null}
        </div>
      </td>
      <td>
        <div class="car-row__setup">
          {row.setupMetrics.map((metric) => (
            <div key={metric.labelText} class="car-row__setup-item">
              <span class="car-row__setup-label">{metric.labelText}</span>
              <span class="car-row__setup-value">
                {metric.isCode ? <code>{metric.valueText}</code> : metric.valueText}
              </span>
            </div>
          ))}
        </div>
      </td>
      <td>
        <div class="car-list-actions">
          {primaryAction ? (
            <button
              type="button"
              class={primaryAction.className}
              data-car-action={primaryAction.type}
              data-car-id={row.carId}
              onClick={() =>
                handleCarsListAction(actions, {
                  type: primaryAction.type,
                  carId: row.carId,
                })}
            >
              {primaryAction.labelText}
            </button>
          ) : null}
          <button
            type="button"
            class="btn btn--danger-quiet car-delete-btn"
            data-car-action="delete"
            data-car-id={row.carId}
            onClick={() => handleCarsListAction(actions, { type: "delete", carId: row.carId })}
          >
            {row.deleteLabelText}
          </button>
        </div>
      </td>
    </tr>
  );
}

function CarsTableBody(props: {
  actions: CarsListPanelActionHandlers | null;
  table: SettingsCarListTableRenderModel | null;
}) {
  const { actions, table } = props;
  const t = useUiTranslation();
  if (table === null) {
    return (
      <tr>
        <td colSpan={3}>
          {t("settings.car.no_cars", "No cars added yet.")}
        </td>
      </tr>
    );
  }
  if (table.kind === "empty") {
    return (
      <tr>
        <td colSpan={3}>
          <div class="settings-table-empty-state">
            <CarsInlineStatePanel actions={actions} state={table.emptyState} />
          </div>
        </td>
      </tr>
    );
  }
  return table.rows.map((row) => (
    <CarsTableRow key={row.carId} actions={actions} row={row} />
  ));
}

function wizardStepState(stepIndex: number, currentStep: number): "active" | "done" | "upcoming" {
  if (stepIndex === currentStep) {
    return "active";
  }
  return stepIndex < currentStep ? "done" : "upcoming";
}

function wizardOptionAttributeProps(
  attribute: CarsWizardOptionsRenderModel["attribute"],
  value: string,
): Record<string, string> {
  switch (attribute) {
    case "data-idx":
      return { "data-idx": value };
    case "data-tire-idx":
      return { "data-tire-idx": value };
    default:
      return { "data-value": value };
  }
}

function WizardOptionButton(props: {
  item: CarsWizardOptionItem;
  attribute: CarsWizardOptionsRenderModel["attribute"];
  onSelect?: () => void;
  optionRef?: (element: HTMLButtonElement | null) => void;
}) {
  const { attribute, item, onSelect, optionRef } = props;
  return (
    <button
      type="button"
      class="wiz-opt"
      data-selected={item.selected ? "true" : undefined}
      aria-pressed={item.selected ? "true" : "false"}
      onClick={onSelect}
      ref={optionRef}
      {...wizardOptionAttributeProps(attribute, item.value)}
    >
      <span>{item.labelText}</span>
      {item.detailText ? <span class="wiz-opt-detail">{item.detailText}</span> : null}
    </button>
  );
}

function WizardOptions(props: {
  firstOptionRef?: (element: HTMLButtonElement | null) => void;
  id: string;
  onSelectOption?: (item: CarsWizardOptionItem) => void;
  section: CarsWizardOptionsRenderModel;
}) {
  const { firstOptionRef, id, onSelectOption, section } = props;
  const className = section.layout === "list"
    ? "wizard-options wizard-options--list"
    : "wizard-options";
  return (
    <div class={className} id={id}>
      {section.messageText ? <em>{section.messageText}</em> : null}
      {section.options.map((item, index) => (
        <WizardOptionButton
          key={`${section.attribute}-${item.value}`}
          attribute={section.attribute}
          item={item}
          onSelect={() => onSelectOption?.(item)}
          optionRef={index === 0 ? firstOptionRef : undefined}
        />
      ))}
    </div>
  );
}

function WizardSummaryPanel(props: { summary: CarsWizardRenderModel["summary"] }) {
  const { summary } = props;
  return (
    <div id="wizardSummaryPanel">
      <div class="wizard-summary-preview">
        <div class="wizard-summary-preview__label">{summary.profileNameLabelText}</div>
        <div class="wizard-summary-preview__value">{summary.profileNameValueText}</div>
      </div>
      <dl class="wizard-summary-list">
        {summary.rows.map((row) => (
          <div key={row.labelText} class="wizard-summary-item">
            <dt>{row.labelText}</dt>
            <dd>{row.valueText}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function CarsPanel(props: {
  state: ReadonlySignal<CarsPanelBridgeState>;
  wizardFocusRequest: ReadonlySignal<CarsWizardFocusRequest | null>;
}) {
  const state = props.state.value;
  const wizardFocusRequest = props.wizardFocusRequest.value;
  const t = useUiTranslation();
  const model = state.model?.value ?? DEFAULT_CARS_PANEL_MODEL;
  const wizardModel = state.wizardModel?.value ?? createClosedCarsWizardRenderModel();
  const addCarBtnRef = useRef<HTMLButtonElement | null>(null);
  const addCarWizardRef = useRef<HTMLDivElement | null>(null);
  const wizardCloseBtnRef = useRef<HTMLButtonElement | null>(null);
  const wizardCustomBrandInputRef = useRef<HTMLInputElement | null>(null);
  const wizardCustomModelInputRef = useRef<HTMLInputElement | null>(null);
  const wizardCustomTypeInputRef = useRef<HTMLInputElement | null>(null);
  const wizardManualAddBtnRef = useRef<HTMLButtonElement | null>(null);
  const wizFinalDriveInputRef = useRef<HTMLInputElement | null>(null);
  const wizGearRatioInputRef = useRef<HTMLInputElement | null>(null);
  const wizRimInputRef = useRef<HTMLInputElement | null>(null);
  const wizTireAspectInputRef = useRef<HTMLInputElement | null>(null);
  const wizTireWidthInputRef = useRef<HTMLInputElement | null>(null);
  const optionRefs = useRef<CarsWizardOptionRefs>({
    brandOption: null,
    gearboxOption: null,
    modelOption: null,
    tireOption: null,
    typeOption: null,
    variantOption: null,
  });
  const lastReturnFocusTargetRef = useRef<HTMLElement | null>(null);
  const lastWizardOpenState = useSignal(wizardModel.isOpen);

  useEffect(() => {
    const wasOpen = lastWizardOpenState.value;
    if (wizardModel.isOpen && !wasOpen) {
      const activeElement = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
      lastReturnFocusTargetRef.current =
        activeElement && activeElement !== document.body ? activeElement : addCarBtnRef.current;
      if (addCarWizardRef.current) {
        addCarWizardRef.current.scrollTop = 0;
      }
    }
    if (!wizardModel.isOpen && wasOpen) {
      const target = lastReturnFocusTargetRef.current;
      const safeTarget = target && document.contains(target) ? target : addCarBtnRef.current;
      focusElement(safeTarget);
      lastReturnFocusTargetRef.current = null;
    }
    lastWizardOpenState.value = wizardModel.isOpen;
  }, [wizardModel.isOpen]);

  useEffect(() => {
    if (!wizardModel.isOpen) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }
      event.preventDefault();
      state.wizardActions?.onAction({ type: "close" });
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [wizardModel.isOpen, state.wizardActions]);

  useEffect(() => {
    if (!wizardFocusRequest) {
      return;
    }
    focusElement(
      resolveWizardFocusTarget(wizardFocusRequest.target, {
        closeButton: wizardCloseBtnRef.current,
        customBrandInput: wizardCustomBrandInputRef.current,
        customModelInput: wizardCustomModelInputRef.current,
        customTypeInput: wizardCustomTypeInputRef.current,
        finalDriveInput: wizFinalDriveInputRef.current,
        manualAddButton: wizardManualAddBtnRef.current,
        optionRefs: optionRefs.current,
        rimInput: wizRimInputRef.current,
        tireAspectInput: wizTireAspectInputRef.current,
        tireWidthInput: wizTireWidthInputRef.current,
        topGearInput: wizGearRatioInputRef.current,
      }),
    );
  }, [wizardFocusRequest]);

  function emitManualInputs(
    field: keyof CarsFeatureManualInputState,
    value: string,
  ): void {
    state.wizardActions?.onAction({
      type: "manual-inputs-changed",
      inputs: {
        ...wizardModel.manualInputs,
        [field]: value,
      },
    });
  }

  return (
    <>
      <div class="panel card">
        <div class="car-tab-header">
          <strong>
            {t("settings.car.manage", "Manage Cars")}
          </strong>
          <button
            id="addCarBtn"
            class="btn btn--success"

            onClick={() => state.wizardActions?.onAction({ type: "open" })}
            ref={addCarBtnRef}
          >
            {t("settings.car.add_new", "+ Add Car")}
          </button>
        </div>
        <div class="subtle">
          {t(
            "settings.car.hint",
            "Add cars from the library or enter specs manually. Activate a car to use it for analysis.",
          )}
        </div>
        <div id="carSelectionGuidance" hidden={model.guidance === null}>
          {model.guidance ? (
            <CarsInlineStatePanel actions={state.actions} state={model.guidance} />
          ) : null}
        </div>
        <div class="settings-table-wrap">
          <table class="car-list-table settings-entity-table settings-entity-table--cars">
            <thead>
              <tr>
                <th>
                  {t("settings.car.col_name", "Name")}
                </th>
                <th>
                  {t("settings.car.col_setup", "Setup")}
                </th>
                <th>
                  {t("settings.car.col_actions", "Actions")}
                </th>
              </tr>
            </thead>
            <tbody id="carListBody">
              <CarsTableBody actions={state.actions} table={model.table} />
            </tbody>
          </table>
        </div>
      </div>

      <div class="wizard-modal-layer" hidden={!wizardModel.isOpen}>
        <div
          id="wizardBackdrop"
          class="wizard-backdrop"
          hidden={!wizardModel.isOpen}
          onClick={() => state.wizardActions?.onAction({ type: "close" })}
        />
        <div
          id="addCarWizard"
          class="panel card add-car-wizard"
          hidden={!wizardModel.isOpen}
          role="dialog"
          aria-modal="true"
          aria-labelledby="wizardTitle"
          data-spec-branch={wizardModel.specBranch ?? undefined}
          ref={addCarWizardRef}
        >
          <div class="wizard-header">
            <div class="wizard-header__text">
              <strong id="wizardTitle">
                {t("settings.car.add_title", "Add a Car")}
              </strong>
              <div class="subtle">
                {t(
                  "settings.car.wizard_intro",
                  "Use the library when it fits, or branch into manual specs without losing your place.",
                )}
              </div>
              <div id="wizardProgressText" class="wizard-progress-text">
                {wizardModel.progressText}
              </div>
            </div>
            <button
              id="wizardCloseBtn"
              class="btn btn--muted wizard-close"
              aria-label="Close wizard"
              onClick={() => state.wizardActions?.onAction({ type: "close" })}
              ref={wizardCloseBtnRef}
            >
              {"\u00d7"}
            </button>
          </div>
          <div class="wizard-shell">
            <div class="wizard-main">
              <div class="wizard-steps">
                <div class="wizard-step-indicators" aria-label="Add car progress">
                  {WIZARD_STEP_LABELS.map((label, index) => (
                    <span
                      key={label.key}
                      class="wizard-step-dot"
                      data-step={String(index)}
                      data-step-state={wizardStepState(index, wizardModel.step)}
                      aria-current={index === wizardModel.step ? "step" : undefined}
                    >
                      <span class="wizard-step-dot__number">{index + 1}</span>
                      <span class="wizard-step-dot__label">
                        {t(label.key, label.fallback)}
                      </span>
                    </span>
                  ))}
                </div>

                <div id="wizardStep0" class="wizard-step" hidden={wizardModel.step !== 0}>
                  <h3>
                    {t("settings.car.step_brand", "Select Brand")}
                  </h3>
                  <WizardOptions
                    id="wizardBrandList"
                    onSelectOption={(item) => {
                      state.wizardActions?.onAction({
                        type: "select-brand",
                        value: item.value,
                      });
                    }}
                    section={wizardModel.brandOptions}
                    firstOptionRef={(element) => {
                      optionRefs.current.brandOption = element;
                    }}
                  />
                  <div class="wizard-custom">
                    <label>
                      {t("settings.car.or_custom_brand", "Or type a custom brand:")}
                    </label>
                    <input
                      id="wizardCustomBrand"
                      type="text"
                      maxLength={32}
                      placeholder="e.g. Mercedes-Benz"
                      ref={wizardCustomBrandInputRef}
                    />
                    <button
                      id="wizardCustomBrandBtn"
                      class="btn btn--primary"

                      onClick={() =>
                        state.wizardActions?.onAction({
                          type: "submit-custom-brand",
                          value: wizardCustomBrandInputRef.current?.value?.trim() ?? "",
                        })}
                    >
                      {t("settings.car.use_custom", "Use Custom")}
                    </button>
                  </div>
                </div>

                <div id="wizardStep1" class="wizard-step" hidden={wizardModel.step !== 1}>
                  <h3>
                    {t("settings.car.step_type", "Select Type")}
                  </h3>
                  <WizardOptions
                    id="wizardTypeList"
                    onSelectOption={(item) => {
                      state.wizardActions?.onAction({
                        type: "select-type",
                        value: item.value,
                      });
                    }}
                    section={wizardModel.typeOptions}
                    firstOptionRef={(element) => {
                      optionRefs.current.typeOption = element;
                    }}
                  />
                  <div class="wizard-custom">
                    <label>
                      {t("settings.car.or_custom_type", "Or type a custom type:")}
                    </label>
                    <input
                      id="wizardCustomType"
                      type="text"
                      maxLength={32}
                      placeholder="e.g. Van"
                      ref={wizardCustomTypeInputRef}
                    />
                    <button
                      id="wizardCustomTypeBtn"
                      class="btn btn--primary"

                      onClick={() =>
                        state.wizardActions?.onAction({
                          type: "submit-custom-type",
                          value: wizardCustomTypeInputRef.current?.value?.trim() ?? "",
                        })}
                    >
                      {t("settings.car.use_custom", "Use Custom")}
                    </button>
                  </div>
                </div>

                <div id="wizardStep2" class="wizard-step" hidden={wizardModel.step !== 2}>
                  <h3>
                    {t("settings.car.step_model", "Select Model")}
                  </h3>
                  <WizardOptions
                    id="wizardModelList"
                    onSelectOption={(item) => {
                      const index = parseWizardOptionIndex(item.value);
                      if (index == null) {
                        return;
                      }
                      state.wizardActions?.onAction({
                        type: "select-model",
                        index,
                      });
                    }}
                    section={wizardModel.modelOptions}
                    firstOptionRef={(element) => {
                      optionRefs.current.modelOption = element;
                    }}
                  />
                  <div class="wizard-custom wizard-custom--branch">
                    <strong class="wizard-branch-label">
                      {t("settings.car.manual_branch_title", "Manual specs branch")}
                    </strong>
                    <div class="subtle wizard-branch-note">
                      {t(
                        "settings.car.manual_model_note",
                        "Skip library variants and finish with your own wheel and gearbox values.",
                      )}
                    </div>
                    <label>
                      {t("settings.car.or_custom_model", "Or type a custom model:")}
                    </label>
                    <input
                      id="wizardCustomModel"
                      type="text"
                      maxLength={64}
                      placeholder="e.g. C-Class W205"
                      ref={wizardCustomModelInputRef}
                    />
                    <button
                      id="wizardCustomModelBtn"
                      class="btn btn--primary"

                      onClick={() =>
                        state.wizardActions?.onAction({
                          type: "submit-custom-model",
                          value: wizardCustomModelInputRef.current?.value?.trim() ?? "",
                        })}
                    >
                      {t("settings.car.use_custom", "Use Custom")}
                    </button>
                  </div>
                </div>

                <div id="wizardStep3" class="wizard-step" hidden={wizardModel.step !== 3}>
                  <h3>
                    {t("settings.car.step_variant", "Select Variant")}
                  </h3>
                  <WizardOptions
                    id="wizardVariantList"
                    onSelectOption={(item) => {
                      const index = parseWizardOptionIndex(item.value);
                      if (index == null) {
                        return;
                      }
                      state.wizardActions?.onAction({
                        type: "select-variant",
                        index,
                      });
                    }}
                    section={wizardModel.variantOptions}
                    firstOptionRef={(element) => {
                      optionRefs.current.variantOption = element;
                    }}
                  />
                </div>

                <div id="wizardStep4" class="wizard-step" hidden={wizardModel.step !== 4}>
                  <div class="wizard-branch-card wizard-branch-card--library">
                    <div class="wizard-branch-card__header">
                      <strong class="wizard-branch-label">
                        {t("settings.car.library_branch_title", "Library-matched specs")}
                      </strong>
                      <div class="subtle wizard-branch-note">
                        {t(
                          "settings.car.library_branch_note",
                          "Choose the tire and gearbox that match this car. Finish stays pinned below.",
                        )}
                      </div>
                    </div>
                    <h3>
                      {t("settings.car.step_wheels", "Select Wheels")}
                    </h3>
                    <WizardOptions
                      id="wizardTireList"
                      onSelectOption={(item) => {
                        const index = parseWizardOptionIndex(item.value);
                        if (index == null) {
                          return;
                        }
                        state.wizardActions?.onAction({
                          type: "select-tire",
                          index,
                        });
                      }}
                      section={wizardModel.tireOptions}
                      firstOptionRef={(element) => {
                        optionRefs.current.tireOption = element;
                      }}
                    />
                    <h3 class="wizard-section-title">
                      {t("settings.car.step_gearbox", "Select Gearbox")}
                    </h3>
                    <WizardOptions
                      id="wizardGearboxList"
                      onSelectOption={(item) => {
                        const index = parseWizardOptionIndex(item.value);
                        if (index == null) {
                          return;
                        }
                        state.wizardActions?.onAction({
                          type: "select-gearbox",
                          index,
                        });
                      }}
                      section={wizardModel.gearboxOptions}
                      firstOptionRef={(element) => {
                        optionRefs.current.gearboxOption = element;
                      }}
                    />
                  </div>
                  <div class="wizard-branch-divider">
                    <span>
                      {t("settings.car.branch_divider", "Or switch to the manual branch")}
                    </span>
                  </div>
                  <div class="wizard-branch-card wizard-branch-card--manual wizard-custom-specs">
                    <div class="wizard-branch-card__header">
                      <strong class="wizard-branch-label">
                        {t("settings.car.manual_branch_title", "Manual specs branch")}
                      </strong>
                      <div
                        class="subtle wizard-custom-specs__note"

                      >
                        {t(
                          "settings.car.manual_specs_note",
                          "Use this branch when the library stops short or you already know the wheel and gearbox measurements.",
                        )}
                      </div>
                    </div>
                    <div class="settings-subgrid">
                      <div class="field">
                        <label htmlFor="wizTireWidth">
                          {t("settings.tire_width", "Tire Width (mm)")}
                        </label>
                        <input
                          id="wizTireWidth"
                          type="number"
                          min="100"
                          step="1"
                          value={wizardModel.manualInputs.tireWidth}
                          onInput={(event) => emitManualInputs("tireWidth", event.currentTarget.value)}
                          ref={wizTireWidthInputRef}
                        />
                      </div>
                      <div class="field">
                        <label htmlFor="wizTireAspect">
                          {t("settings.tire_aspect", "Tire Aspect (%)")}
                        </label>
                        <input
                          id="wizTireAspect"
                          type="number"
                          min="20"
                          step="1"
                          value={wizardModel.manualInputs.tireAspect}
                          onInput={(event) => emitManualInputs("tireAspect", event.currentTarget.value)}
                          ref={wizTireAspectInputRef}
                        />
                      </div>
                      <div class="field">
                        <label htmlFor="wizRim">
                          {t("settings.rim_size", "Rim Size (in)")}
                        </label>
                        <input
                          id="wizRim"
                          type="number"
                          min="10"
                          step="0.5"
                          value={wizardModel.manualInputs.rim}
                          onInput={(event) => emitManualInputs("rim", event.currentTarget.value)}
                          ref={wizRimInputRef}
                        />
                      </div>
                      <div class="field">
                        <label htmlFor="wizFinalDrive">
                          {t("settings.final_drive_ratio", "Final Drive Ratio")}
                        </label>
                        <input
                          id="wizFinalDrive"
                          type="number"
                          step="0.01"
                          min="0.1"
                          value={wizardModel.manualInputs.finalDrive}
                          onInput={(event) => emitManualInputs("finalDrive", event.currentTarget.value)}
                          ref={wizFinalDriveInputRef}
                        />
                      </div>
                      <div class="field">
                        <label htmlFor="wizGearRatio">
                          {t("settings.top_gear_ratio", "Top Gear Ratio")}
                        </label>
                        <input
                          id="wizGearRatio"
                          type="number"
                          step="0.01"
                          min="0.1"
                          value={wizardModel.manualInputs.topGear}
                          onInput={(event) => emitManualInputs("topGear", event.currentTarget.value)}
                          ref={wizGearRatioInputRef}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="wizard-nav">
                <div id="wizardActionHint" class="subtle wizard-nav__status" aria-live="polite">
                  {wizardModel.actionHintText}
                </div>
                <div class="wizard-nav__actions">
                  <button
                    id="wizardBackBtn"
                    class="btn btn--muted"
                    hidden={!wizardModel.backVisible}

                    onClick={() => state.wizardActions?.onAction({ type: "back" })}
                  >
                    {t("settings.car.back", "Back")}
                  </button>
                  <button
                    id="wizardManualAddBtn"
                    class="btn btn--success"
                    hidden={!wizardModel.finishVisible}
                    disabled={!wizardModel.finishEnabled}

                    onClick={() => state.wizardActions?.onAction({ type: "finish" })}
                    ref={wizardManualAddBtnRef}
                  >
                    {t("settings.car.finish_add", "Add Car")}
                  </button>
                </div>
              </div>
            </div>

            <aside class="wizard-summary-card" aria-live="polite">
              <div class="wizard-task-callout">
                <strong>
                  {t("settings.car.wizard_task_title", "Guided setup")}
                </strong>
                <div class="subtle">
                  {t(
                    "settings.car.wizard_task_intro",
                    "This flow pauses the rest of Settings so you can build the next analysis profile step by step without losing your place.",
                  )}
                </div>
              </div>
              <div class="wizard-summary-card__title">
                {t("settings.car.wizard_summary_title", "Current selection")}
              </div>
              <div class="subtle">
                {t(
                  "settings.car.wizard_summary_intro",
                  "Your choices stay visible here while the profile comes together.",
                )}
              </div>
              <WizardSummaryPanel summary={wizardModel.summary} />
            </aside>
          </div>
        </div>
      </div>
    </>
  );
}

export function mountCarsPanel(host: HTMLElement): CarsPanelView {
  const bridgeState = signal<CarsPanelBridgeState>({
    actions: null,
    model: null,
    wizardActions: null,
    wizardModel: null,
  });
  const wizardFocusRequest = signal<CarsWizardFocusRequest | null>(null);
  let focusRequestToken = 0;
  render(
    <CarsPanel
      state={bridgeState}
      wizardFocusRequest={wizardFocusRequest}
    />,
    host,
  );

  return {
    list: {
      bindActions(handlers): void {
        bridgeState.value = { ...bridgeState.value, actions: handlers };
      },
      bindModel(model): void {
        bridgeState.value = { ...bridgeState.value, model };
      },
    },
    wizard: {
      bindActions(handlers): void {
        bridgeState.value = { ...bridgeState.value, wizardActions: handlers };
      },
      focus(target): void {
        focusRequestToken += 1;
        wizardFocusRequest.value = { target, token: focusRequestToken };
      },
      bindModel(model): void {
        bridgeState.value = { ...bridgeState.value, wizardModel: model };
      },
    },
  };
}
