import type { CarsFeatureFocusTarget, CarsFeatureManualInputState } from "../features/cars_feature_workflow";
import { useUiTranslation } from "../ui_i18n";
import type {
  CarsWizardOptionItem,
  CarsWizardOptionsRenderModel,
  CarsWizardRenderModel,
} from "./car_wizard_view";

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

export type CarsWizardOptionRefs = {
  brandOption: HTMLButtonElement | null;
  gearboxOption: HTMLButtonElement | null;
  modelOption: HTMLButtonElement | null;
  tireOption: HTMLButtonElement | null;
  typeOption: HTMLButtonElement | null;
  variantOption: HTMLButtonElement | null;
};

export type CarsWizardFocusRequest = {
  target: CarsFeatureFocusTarget;
  token: number;
};

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

export type CarsWizardElementRefs = {
  addCarWizardRef: { current: HTMLDivElement | null };
  optionRefs: { current: CarsWizardOptionRefs };
  wizardCloseBtnRef: { current: HTMLButtonElement | null };
  wizardCustomBrandInputRef: { current: HTMLInputElement | null };
  wizardCustomModelInputRef: { current: HTMLInputElement | null };
  wizardCustomTypeInputRef: { current: HTMLInputElement | null };
  wizardManualAddBtnRef: { current: HTMLButtonElement | null };
  wizFinalDriveInputRef: { current: HTMLInputElement | null };
  wizGearRatioInputRef: { current: HTMLInputElement | null };
  wizRimInputRef: { current: HTMLInputElement | null };
  wizTireAspectInputRef: { current: HTMLInputElement | null };
  wizTireWidthInputRef: { current: HTMLInputElement | null };
};

const WIZARD_STEP_LABELS = [
  { key: "settings.car.step_brand_short", fallback: "Brand" },
  { key: "settings.car.step_type_short", fallback: "Type" },
  { key: "settings.car.step_model_short", fallback: "Model" },
  { key: "settings.car.step_variant_short", fallback: "Variant" },
  { key: "settings.car.step_specs_short", fallback: "Specs" },
] as const;

function parseWizardOptionIndex(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}

export function resolveWizardFocusTarget(
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

function CarsWizardStepNav(props: { step: number }) {
  const { step } = props;
  const t = useUiTranslation();
  return (
    <div class="wizard-step-indicators" aria-label="Add car progress">
      {WIZARD_STEP_LABELS.map((label, index) => (
        <span
          key={label.key}
          class="wizard-step-dot"
          data-step={String(index)}
          data-step-state={wizardStepState(index, step)}
          aria-current={index === step ? "step" : undefined}
        >
          <span class="wizard-step-dot__number">{index + 1}</span>
          <span class="wizard-step-dot__label">
            {t(label.key, label.fallback)}
          </span>
        </span>
      ))}
    </div>
  );
}

function CarsManualInputForm(props: {
  emitManualInputs(field: keyof CarsFeatureManualInputState, value: string): void;
  refs: CarsWizardElementRefs;
  wizardModel: CarsWizardRenderModel;
}) {
  const { emitManualInputs, refs, wizardModel } = props;
  const t = useUiTranslation();
  return (
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
          ref={refs.wizTireWidthInputRef}
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
          ref={refs.wizTireAspectInputRef}
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
          ref={refs.wizRimInputRef}
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
          ref={refs.wizFinalDriveInputRef}
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
          ref={refs.wizGearRatioInputRef}
        />
      </div>
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

export function CarsWizardPanel(props: {
  actions: CarsFeatureInteractionHandlers | null;
  refs: CarsWizardElementRefs;
  wizardModel: CarsWizardRenderModel;
}) {
  const { actions, refs, wizardModel } = props;
  const t = useUiTranslation();

  function closeWizard(): void {
    actions?.onAction({ type: "close" });
  }

  function emitManualInputs(
    field: keyof CarsFeatureManualInputState,
    value: string,
  ): void {
    actions?.onAction({
      type: "manual-inputs-changed",
      inputs: {
        ...wizardModel.manualInputs,
        [field]: value,
      },
    });
  }

  function handleWizardKeyDown(event: KeyboardEvent): void {
    if (event.key !== "Escape") {
      return;
    }
    event.preventDefault();
    closeWizard();
  }

  return (
    <div class="wizard-modal-layer" hidden={!wizardModel.isOpen}>
      <div
        id="wizardBackdrop"
        class="wizard-backdrop"
        hidden={!wizardModel.isOpen}
        onClick={closeWizard}
      />
      <div
        id="addCarWizard"
        class="panel card add-car-wizard"
        hidden={!wizardModel.isOpen}
        role="dialog"
        aria-modal="true"
        aria-labelledby="wizardTitle"
        data-spec-branch={wizardModel.specBranch ?? undefined}
        tabIndex={-1}
        onKeyDown={handleWizardKeyDown}
        ref={refs.addCarWizardRef}
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
            onClick={closeWizard}
            ref={refs.wizardCloseBtnRef}
          >
            {"\u00d7"}
          </button>
        </div>
        <div class="wizard-shell">
          <div class="wizard-main">
            <div class="wizard-steps">
              <CarsWizardStepNav step={wizardModel.step} />

              <div id="wizardStep0" class="wizard-step" hidden={wizardModel.step !== 0}>
                <h3>
                  {t("settings.car.step_brand", "Select Brand")}
                </h3>
                <WizardOptions
                  id="wizardBrandList"
                  onSelectOption={(item) => {
                    actions?.onAction({
                      type: "select-brand",
                      value: item.value,
                    });
                  }}
                  section={wizardModel.brandOptions}
                  firstOptionRef={(element) => {
                    refs.optionRefs.current.brandOption = element;
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
                    ref={refs.wizardCustomBrandInputRef}
                  />
                  <button
                    id="wizardCustomBrandBtn"
                    class="btn btn--primary"
                    onClick={() =>
                      actions?.onAction({
                        type: "submit-custom-brand",
                        value: refs.wizardCustomBrandInputRef.current?.value?.trim() ?? "",
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
                    actions?.onAction({
                      type: "select-type",
                      value: item.value,
                    });
                  }}
                  section={wizardModel.typeOptions}
                  firstOptionRef={(element) => {
                    refs.optionRefs.current.typeOption = element;
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
                    ref={refs.wizardCustomTypeInputRef}
                  />
                  <button
                    id="wizardCustomTypeBtn"
                    class="btn btn--primary"
                    onClick={() =>
                      actions?.onAction({
                        type: "submit-custom-type",
                        value: refs.wizardCustomTypeInputRef.current?.value?.trim() ?? "",
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
                    actions?.onAction({
                      type: "select-model",
                      index,
                    });
                  }}
                  section={wizardModel.modelOptions}
                  firstOptionRef={(element) => {
                    refs.optionRefs.current.modelOption = element;
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
                    ref={refs.wizardCustomModelInputRef}
                  />
                  <button
                    id="wizardCustomModelBtn"
                    class="btn btn--primary"
                    onClick={() =>
                      actions?.onAction({
                        type: "submit-custom-model",
                        value: refs.wizardCustomModelInputRef.current?.value?.trim() ?? "",
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
                    actions?.onAction({
                      type: "select-variant",
                      index,
                    });
                  }}
                  section={wizardModel.variantOptions}
                  firstOptionRef={(element) => {
                    refs.optionRefs.current.variantOption = element;
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
                      actions?.onAction({
                        type: "select-tire",
                        index,
                      });
                    }}
                    section={wizardModel.tireOptions}
                    firstOptionRef={(element) => {
                      refs.optionRefs.current.tireOption = element;
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
                      actions?.onAction({
                        type: "select-gearbox",
                        index,
                      });
                    }}
                    section={wizardModel.gearboxOptions}
                    firstOptionRef={(element) => {
                      refs.optionRefs.current.gearboxOption = element;
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
                    <div class="subtle wizard-custom-specs__note">
                      {t(
                        "settings.car.manual_specs_note",
                        "Use this branch when the library stops short or you already know the wheel and gearbox measurements.",
                      )}
                    </div>
                  </div>
                  <CarsManualInputForm
                    emitManualInputs={emitManualInputs}
                    refs={refs}
                    wizardModel={wizardModel}
                  />
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
                  onClick={() => actions?.onAction({ type: "back" })}
                >
                  {t("settings.car.back", "Back")}
                </button>
                <button
                  id="wizardManualAddBtn"
                  class="btn btn--success"
                  hidden={!wizardModel.finishVisible}
                  disabled={!wizardModel.finishEnabled}
                  onClick={() => actions?.onAction({ type: "finish" })}
                  ref={refs.wizardManualAddBtnRef}
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
  );
}
