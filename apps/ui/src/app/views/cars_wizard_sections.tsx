import type { ComponentChildren } from "preact";

import type { CarsFeatureManualInputState } from "../features/cars_manual_input";
import { useUiTranslation } from "../ui_i18n";
import type {
  CarsWizardOptionItem,
  CarsWizardOptionsRenderModel,
  CarsWizardRenderModel,
} from "./car_wizard_view";
import type { CarsWizardElementRefs } from "./cars_wizard_focus";

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

function submitCurrentInputValue(
  inputRef: { current: HTMLInputElement | null },
  onSubmit: (value: string) => void,
): void {
  onSubmit(inputRef.current?.value?.trim() ?? "");
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

function WizardCustomEntry(props: {
  buttonId: string;
  className?: string;
  inputId: string;
  inputRef: { current: HTMLInputElement | null };
  intro?: ComponentChildren;
  labelText: string;
  maxLength: number;
  placeholder: string;
  onSubmit(value: string): void;
}) {
  const { buttonId, className, inputId, inputRef, intro, labelText, maxLength, onSubmit, placeholder } = props;
  const t = useUiTranslation();
  return (
    <div class={className ?? "wizard-custom"}>
      {intro}
      <label>{labelText}</label>
      <input
        id={inputId}
        type="text"
        maxLength={maxLength}
        placeholder={placeholder}
        ref={inputRef}
      />
      <button
        id={buttonId}
        class="btn btn--primary"
        onClick={() => submitCurrentInputValue(inputRef, onSubmit)}
      >
        {t("settings.car.use_custom", "Use Custom")}
      </button>
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

function WizardBrandStep(props: {
  hidden: boolean;
  refs: CarsWizardElementRefs;
  section: CarsWizardOptionsRenderModel;
  onSelectBrand(value: string): void;
  onSubmitCustomBrand(value: string): void;
}) {
  const { hidden, onSelectBrand, onSubmitCustomBrand, refs, section } = props;
  const t = useUiTranslation();
  return (
    <div id="wizardStep0" class="wizard-step" hidden={hidden}>
      <h3>
        {t("settings.car.step_brand", "Select Brand")}
      </h3>
      <WizardOptions
        id="wizardBrandList"
        onSelectOption={(item) => onSelectBrand(item.value)}
        section={section}
        firstOptionRef={(element) => {
          refs.optionRefs.current.brandOption = element;
        }}
      />
      <WizardCustomEntry
        buttonId="wizardCustomBrandBtn"
        inputId="wizardCustomBrand"
        inputRef={refs.wizardCustomBrandInputRef}
        labelText={t("settings.car.or_custom_brand", "Or type a custom brand:")}
        maxLength={32}
        onSubmit={onSubmitCustomBrand}
        placeholder="e.g. Mercedes-Benz"
      />
    </div>
  );
}

function WizardTypeStep(props: {
  hidden: boolean;
  refs: CarsWizardElementRefs;
  section: CarsWizardOptionsRenderModel;
  onSelectType(value: string): void;
  onSubmitCustomType(value: string): void;
}) {
  const { hidden, onSelectType, onSubmitCustomType, refs, section } = props;
  const t = useUiTranslation();
  return (
    <div id="wizardStep1" class="wizard-step" hidden={hidden}>
      <h3>
        {t("settings.car.step_type", "Select Type")}
      </h3>
      <WizardOptions
        id="wizardTypeList"
        onSelectOption={(item) => onSelectType(item.value)}
        section={section}
        firstOptionRef={(element) => {
          refs.optionRefs.current.typeOption = element;
        }}
      />
      <WizardCustomEntry
        buttonId="wizardCustomTypeBtn"
        inputId="wizardCustomType"
        inputRef={refs.wizardCustomTypeInputRef}
        labelText={t("settings.car.or_custom_type", "Or type a custom type:")}
        maxLength={32}
        onSubmit={onSubmitCustomType}
        placeholder="e.g. Van"
      />
    </div>
  );
}

function WizardModelStep(props: {
  hidden: boolean;
  refs: CarsWizardElementRefs;
  section: CarsWizardOptionsRenderModel;
  onSelectModel(index: number): void;
  onSubmitCustomModel(value: string): void;
}) {
  const { hidden, onSelectModel, onSubmitCustomModel, refs, section } = props;
  const t = useUiTranslation();
  return (
    <div id="wizardStep2" class="wizard-step" hidden={hidden}>
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
          onSelectModel(index);
        }}
        section={section}
        firstOptionRef={(element) => {
          refs.optionRefs.current.modelOption = element;
        }}
      />
      <WizardCustomEntry
        buttonId="wizardCustomModelBtn"
        className="wizard-custom wizard-custom--branch"
        inputId="wizardCustomModel"
        inputRef={refs.wizardCustomModelInputRef}
        intro={(
          <>
            <strong class="wizard-branch-label">
              {t("settings.car.manual_branch_title", "Manual specs branch")}
            </strong>
            <div class="subtle wizard-branch-note">
              {t(
                "settings.car.manual_model_note",
                "Skip library variants and finish with your own wheel and gearbox values.",
              )}
            </div>
          </>
        )}
        labelText={t("settings.car.or_custom_model", "Or type a custom model:")}
        maxLength={64}
        onSubmit={onSubmitCustomModel}
        placeholder="e.g. C-Class W205"
      />
    </div>
  );
}

function WizardVariantStep(props: {
  hidden: boolean;
  refs: CarsWizardElementRefs;
  section: CarsWizardOptionsRenderModel;
  onSelectVariant(index: number): void;
}) {
  const { hidden, onSelectVariant, refs, section } = props;
  const t = useUiTranslation();
  return (
    <div id="wizardStep3" class="wizard-step" hidden={hidden}>
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
          onSelectVariant(index);
        }}
        section={section}
        firstOptionRef={(element) => {
          refs.optionRefs.current.variantOption = element;
        }}
      />
    </div>
  );
}

function WizardSpecsStep(props: {
  emitManualInputs(field: keyof CarsFeatureManualInputState, value: string): void;
  hidden: boolean;
  refs: CarsWizardElementRefs;
  wizardModel: CarsWizardRenderModel;
  onSelectGearbox(index: number): void;
  onSelectTire(index: number): void;
}) {
  const { emitManualInputs, hidden, onSelectGearbox, onSelectTire, refs, wizardModel } = props;
  const t = useUiTranslation();
  return (
    <div id="wizardStep4" class="wizard-step" hidden={hidden}>
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
            onSelectTire(index);
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
            onSelectGearbox(index);
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
  );
}

export function CarsWizardStepNav(props: { step: number }) {
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

export function CarsWizardSteps(props: {
  emitManualInputs(field: keyof CarsFeatureManualInputState, value: string): void;
  refs: CarsWizardElementRefs;
  wizardModel: CarsWizardRenderModel;
  onSelectBrand(value: string): void;
  onSelectGearbox(index: number): void;
  onSelectModel(index: number): void;
  onSelectTire(index: number): void;
  onSelectType(value: string): void;
  onSelectVariant(index: number): void;
  onSubmitCustomBrand(value: string): void;
  onSubmitCustomModel(value: string): void;
  onSubmitCustomType(value: string): void;
}) {
  const {
    emitManualInputs,
    onSelectBrand,
    onSelectGearbox,
    onSelectModel,
    onSelectTire,
    onSelectType,
    onSelectVariant,
    onSubmitCustomBrand,
    onSubmitCustomModel,
    onSubmitCustomType,
    refs,
    wizardModel,
  } = props;

  return (
    <>
      <WizardBrandStep
        hidden={wizardModel.step !== 0}
        refs={refs}
        section={wizardModel.brandOptions}
        onSelectBrand={onSelectBrand}
        onSubmitCustomBrand={onSubmitCustomBrand}
      />
      <WizardTypeStep
        hidden={wizardModel.step !== 1}
        refs={refs}
        section={wizardModel.typeOptions}
        onSelectType={onSelectType}
        onSubmitCustomType={onSubmitCustomType}
      />
      <WizardModelStep
        hidden={wizardModel.step !== 2}
        refs={refs}
        section={wizardModel.modelOptions}
        onSelectModel={onSelectModel}
        onSubmitCustomModel={onSubmitCustomModel}
      />
      <WizardVariantStep
        hidden={wizardModel.step !== 3}
        refs={refs}
        section={wizardModel.variantOptions}
        onSelectVariant={onSelectVariant}
      />
      <WizardSpecsStep
        emitManualInputs={emitManualInputs}
        hidden={wizardModel.step !== 4}
        refs={refs}
        wizardModel={wizardModel}
        onSelectGearbox={onSelectGearbox}
        onSelectTire={onSelectTire}
      />
    </>
  );
}

export function CarsWizardSummaryPanel(props: { summary: CarsWizardRenderModel["summary"] }) {
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
