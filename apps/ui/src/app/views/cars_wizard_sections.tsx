import type { ComponentChildren, JSX } from "preact";
import { useMemo } from "preact/hooks";

import type { CarsFeatureManualInputState } from "../features/cars_manual_input";
import { getUiText as t } from "../ui_i18n";
import {
  useSignalProperties,
  type ReadonlySignal,
} from "../ui_signals";
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
const CARS_WIZARD_STEPS_KEYS = [
  "brandOptions",
  "gearboxOptions",
  "manualInputs",
  "modelOptions",
  "step",
  "tireOptions",
  "typeOptions",
  "variantOptions",
] as const;
const WIZARD_OPTIONS_KEYS = ["attribute", "layout", "messageText", "options"] as const;
const WIZARD_MANUAL_INPUT_KEYS = [
  "finalDrive",
  "rim",
  "tireAspect",
  "tireWidth",
  "topGear",
] as const;
const WIZARD_SUMMARY_KEYS = [
  "profileNameLabelText",
  "profileNameValueText",
  "rows",
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
  input: HTMLInputElement | null,
  onSubmit: (value: string) => void,
): void {
  onSubmit(input?.value?.trim() ?? "");
}

type ManualInputField = keyof CarsFeatureManualInputState;
type ManualInputHandler = (event: JSX.TargetedEvent<HTMLInputElement, Event>) => void;

function createManualInputHandler(
  emitManualInputs: (field: ManualInputField, value: string) => void,
  field: ManualInputField,
): ManualInputHandler {
  return (event) => {
    emitManualInputs(field, event.currentTarget.value);
  };
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
  section: ReadonlySignal<CarsWizardOptionsRenderModel>;
}) {
  const { firstOptionRef, id, onSelectOption } = props;
  const { attribute, layout, messageText, options } = useSignalProperties(
    props.section,
    WIZARD_OPTIONS_KEYS,
  );
  const className = layout.value === "list"
    ? "wizard-options wizard-options--list"
    : "wizard-options";
  return (
    <div class={className} id={id}>
      {messageText.value ? <em>{messageText.value}</em> : null}
      {options.value.map((item, index) => (
        <WizardOptionButton
          key={`${attribute.value}-${item.value}`}
          attribute={attribute.value}
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
  inputKey: "customBrandInput" | "customModelInput" | "customTypeInput";
  intro?: ComponentChildren;
  labelText: string;
  maxLength: number;
  refs: CarsWizardElementRefs;
  placeholder: string;
  onSubmit(value: string): void;
}) {
  const { buttonId, className, inputId, inputKey, intro, labelText, maxLength, onSubmit, placeholder, refs } =
    props;
  return (
    <div class={className ?? "wizard-custom"}>
      {intro}
      <label>{labelText}</label>
      <input
        id={inputId}
        type="text"
        maxLength={maxLength}
        placeholder={placeholder}
        ref={refs.setElementRef(inputKey)}
      />
      <button
        id={buttonId}
        class="btn btn--primary"
        onClick={() => submitCurrentInputValue(refs.elements.current[inputKey], onSubmit)}
      >
        {t("settings.car.use_custom", "Use Custom")}
      </button>
    </div>
  );
}

function CarsManualInputForm(props: {
  emitManualInputs(field: ManualInputField, value: string): void;
  manualInputs: ReadonlySignal<CarsWizardRenderModel["manualInputs"]>;
  refs: CarsWizardElementRefs;
}) {
  const { emitManualInputs, refs } = props;
  const inputHandlers = useMemo<Record<ManualInputField, ManualInputHandler>>(
    () => ({
      tireWidth: createManualInputHandler(emitManualInputs, "tireWidth"),
      tireAspect: createManualInputHandler(emitManualInputs, "tireAspect"),
      rim: createManualInputHandler(emitManualInputs, "rim"),
      finalDrive: createManualInputHandler(emitManualInputs, "finalDrive"),
      topGear: createManualInputHandler(emitManualInputs, "topGear"),
    }),
    [emitManualInputs],
  );
  const { finalDrive, rim, tireAspect, tireWidth, topGear } = useSignalProperties(
    props.manualInputs,
    WIZARD_MANUAL_INPUT_KEYS,
  );
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
          value={tireWidth.value}
          onInput={inputHandlers.tireWidth}
          ref={refs.setElementRef("tireWidthInput")}
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
          value={tireAspect.value}
          onInput={inputHandlers.tireAspect}
          ref={refs.setElementRef("tireAspectInput")}
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
          value={rim.value}
          onInput={inputHandlers.rim}
          ref={refs.setElementRef("rimInput")}
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
          value={finalDrive.value}
          onInput={inputHandlers.finalDrive}
          ref={refs.setElementRef("finalDriveInput")}
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
          value={topGear.value}
          onInput={inputHandlers.topGear}
          ref={refs.setElementRef("topGearInput")}
        />
      </div>
    </div>
  );
}

function WizardBrandStep(props: {
  hidden: boolean;
  refs: CarsWizardElementRefs;
  section: ReadonlySignal<CarsWizardOptionsRenderModel>;
  onSelectBrand(value: string): void;
  onSubmitCustomBrand(value: string): void;
}) {
  const { onSelectBrand, onSubmitCustomBrand, refs, section } = props;
  return (
    <div id="wizardStep0" class="wizard-step" hidden={props.hidden}>
      <h3>
        {t("settings.car.step_brand", "Select Brand")}
      </h3>
      <WizardOptions
        id="wizardBrandList"
        onSelectOption={(item) => onSelectBrand(item.value)}
        section={section}
        firstOptionRef={refs.setElementRef("brandOption")}
      />
      <WizardCustomEntry
        buttonId="wizardCustomBrandBtn"
        inputId="wizardCustomBrand"
        inputKey="customBrandInput"
        labelText={t("settings.car.or_custom_brand", "Or type a custom brand:")}
        maxLength={32}
        onSubmit={onSubmitCustomBrand}
        placeholder="e.g. Mercedes-Benz"
        refs={refs}
      />
    </div>
  );
}

function WizardTypeStep(props: {
  hidden: boolean;
  refs: CarsWizardElementRefs;
  section: ReadonlySignal<CarsWizardOptionsRenderModel>;
  onSelectType(value: string): void;
  onSubmitCustomType(value: string): void;
}) {
  const { onSelectType, onSubmitCustomType, refs, section } = props;
  return (
    <div id="wizardStep1" class="wizard-step" hidden={props.hidden}>
      <h3>
        {t("settings.car.step_type", "Select Type")}
      </h3>
      <WizardOptions
        id="wizardTypeList"
        onSelectOption={(item) => onSelectType(item.value)}
        section={section}
        firstOptionRef={refs.setElementRef("typeOption")}
      />
      <WizardCustomEntry
        buttonId="wizardCustomTypeBtn"
        inputId="wizardCustomType"
        inputKey="customTypeInput"
        labelText={t("settings.car.or_custom_type", "Or type a custom type:")}
        maxLength={32}
        onSubmit={onSubmitCustomType}
        placeholder="e.g. Van"
        refs={refs}
      />
    </div>
  );
}

function WizardModelStep(props: {
  hidden: boolean;
  refs: CarsWizardElementRefs;
  section: ReadonlySignal<CarsWizardOptionsRenderModel>;
  onSelectModel(index: number): void;
  onSubmitCustomModel(value: string): void;
}) {
  const { onSelectModel, onSubmitCustomModel, refs, section } = props;
  return (
    <div id="wizardStep2" class="wizard-step" hidden={props.hidden}>
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
        firstOptionRef={refs.setElementRef("modelOption")}
      />
      <WizardCustomEntry
        buttonId="wizardCustomModelBtn"
        className="wizard-custom wizard-custom--branch"
        inputId="wizardCustomModel"
        inputKey="customModelInput"
        intro={(
          <>
            <strong class="wizard-branch-label">
              {t("settings.car.manual_branch_title", "Manual specs")}
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
        refs={refs}
      />
    </div>
  );
}

function WizardVariantStep(props: {
  hidden: boolean;
  refs: CarsWizardElementRefs;
  section: ReadonlySignal<CarsWizardOptionsRenderModel>;
  onSelectVariant(index: number): void;
}) {
  const { onSelectVariant, refs, section } = props;
  return (
    <div id="wizardStep3" class="wizard-step" hidden={props.hidden}>
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
        firstOptionRef={refs.setElementRef("variantOption")}
      />
    </div>
  );
}

function WizardSpecsStep(props: {
  emitManualInputs(field: keyof CarsFeatureManualInputState, value: string): void;
  gearboxOptions: ReadonlySignal<CarsWizardOptionsRenderModel>;
  hidden: boolean;
  manualInputs: ReadonlySignal<CarsWizardRenderModel["manualInputs"]>;
  refs: CarsWizardElementRefs;
  onSelectGearbox(index: number): void;
  onSelectTire(index: number): void;
  tireOptions: ReadonlySignal<CarsWizardOptionsRenderModel>;
}) {
  const {
    emitManualInputs,
    gearboxOptions,
    onSelectGearbox,
    onSelectTire,
    refs,
    tireOptions,
  } = props;
  return (
    <div id="wizardStep4" class="wizard-step" hidden={props.hidden}>
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
        section={tireOptions}
        firstOptionRef={refs.setElementRef("tireOption")}
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
        section={gearboxOptions}
        firstOptionRef={refs.setElementRef("gearboxOption")}
      />
      </div>
      <div class="wizard-branch-divider">
        <span>
          {t("settings.car.branch_divider", "Or switch to manual specs")}
        </span>
      </div>
      <div class="wizard-branch-card wizard-branch-card--manual wizard-custom-specs">
        <div class="wizard-branch-card__header">
          <strong class="wizard-branch-label">
            {t("settings.car.manual_branch_title", "Manual specs")}
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
          manualInputs={props.manualInputs}
          refs={refs}
        />
      </div>
    </div>
  );
}

export function CarsWizardStepNav(props: { step: ReadonlySignal<number> }) {
  return (
    <div class="wizard-step-indicators" aria-label="Add car progress">
      {WIZARD_STEP_LABELS.map((label, index) => (
        <span
          key={label.key}
          class="wizard-step-dot"
          data-step={String(index)}
          data-step-state={wizardStepState(index, props.step.value)}
          aria-current={index === props.step.value ? "step" : undefined}
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
  wizardModel: ReadonlySignal<CarsWizardRenderModel>;
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
  } = props;
  const {
    brandOptions,
    gearboxOptions,
    manualInputs,
    modelOptions,
    step,
    tireOptions,
    typeOptions,
    variantOptions,
  } = useSignalProperties(props.wizardModel, CARS_WIZARD_STEPS_KEYS);
  const brandHidden = step.value !== 0;
  const typeHidden = step.value !== 1;
  const modelHidden = step.value !== 2;
  const variantHidden = step.value !== 3;
  const specsHidden = step.value !== 4;

  return (
    <>
      <WizardBrandStep
        hidden={brandHidden}
        refs={refs}
        section={brandOptions}
        onSelectBrand={onSelectBrand}
        onSubmitCustomBrand={onSubmitCustomBrand}
      />
      <WizardTypeStep
        hidden={typeHidden}
        refs={refs}
        section={typeOptions}
        onSelectType={onSelectType}
        onSubmitCustomType={onSubmitCustomType}
      />
      <WizardModelStep
        hidden={modelHidden}
        refs={refs}
        section={modelOptions}
        onSelectModel={onSelectModel}
        onSubmitCustomModel={onSubmitCustomModel}
      />
      <WizardVariantStep
        hidden={variantHidden}
        refs={refs}
        section={variantOptions}
        onSelectVariant={onSelectVariant}
      />
      <WizardSpecsStep
        emitManualInputs={emitManualInputs}
        gearboxOptions={gearboxOptions}
        hidden={specsHidden}
        manualInputs={manualInputs}
        refs={refs}
        onSelectGearbox={onSelectGearbox}
        onSelectTire={onSelectTire}
        tireOptions={tireOptions}
      />
    </>
  );
}

export function CarsWizardSummaryPanel(props: {
  summary: ReadonlySignal<CarsWizardRenderModel["summary"]>;
}) {
  const { profileNameLabelText, profileNameValueText, rows } = useSignalProperties(
    props.summary,
    WIZARD_SUMMARY_KEYS,
  );
  return (
    <div id="wizardSummaryPanel">
      <div class="wizard-summary-preview">
        <div class="wizard-summary-preview__label">{profileNameLabelText.value}</div>
        <div class="wizard-summary-preview__value">{profileNameValueText.value}</div>
      </div>
      <dl class="wizard-summary-list">
        {rows.value.map((row) => (
          <div key={row.labelText} class="wizard-summary-item">
            <dt>{row.labelText}</dt>
            <dd>{row.valueText}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
