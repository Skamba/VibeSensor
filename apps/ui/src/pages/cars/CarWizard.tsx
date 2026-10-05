import type { ComponentChildren } from "preact";
import { useLayoutEffect, useRef } from "preact/hooks";

import { activeView } from "../../app_store";
import { carCapabilities, type FuelType } from "../../capabilities";
import { provenanceTier } from "../../car_references";
import { fmt } from "../../format";
import { t } from "../../i18n";
import { CapabilityList, ProvenanceChip } from "./CapabilityList";
import { formatCarLibraryTireOption } from "./tires";
import {
  actionHint,
  asksPowertrain,
  canFinish,
  gearboxParts,
  type ManualField,
  progressText,
  type RatioField,
  type RatioPart,
  SPECS_STEP,
  STEP_LABEL_KEYS,
  specProvenance,
  summary,
  variantDetail,
  wizardFuelType,
} from "./wizard_model";
import {
  brandOptions,
  clearRatio,
  closeWizard,
  continueWithManualSpecs,
  editManualInput,
  editTireSize,
  finishWizard,
  type FocusTarget,
  focusRequest,
  gearboxOptions,
  goBack,
  isOpen,
  type LibraryOptions,
  loadCurrentStep,
  manualInputs,
  modelOptions,
  noGearboxesMessage,
  selectBrand,
  selectGearbox,
  selectModel,
  selectPowertrain,
  selectTire,
  selectType,
  selectVariant,
  step,
  submitCustom,
  tireOptions,
  tireSizeText,
  tireSizeUnreadable,
  typeOptions,
  variantOptions,
  wizard,
} from "./wizard_store";

/** Elements a focus request can land on, in order of preference. */
const FOCUS_SELECTORS: Record<FocusTarget, string[]> = {
  "brand-option": ["#wizardBrandList .wiz-opt", "#wizardCustomBrand"],
  close: ["#wizardCloseBtn"],
  "custom-brand": ["#wizardCustomBrand"],
  "custom-model": ["#wizardCustomModel"],
  "custom-type": ["#wizardCustomType"],
  finish: ["#wizardManualAddBtn"],
  "gearbox-option": ["#wizardGearboxList .wiz-opt", "#wizardManualAddBtn"],
  "model-option": ["#wizardModelList .wiz-opt", "#wizardCustomModel"],
  "spec-selection": [
    "#wizardTireList .wiz-opt",
    "#wizardGearboxList .wiz-opt",
    "#wizTireSize",
  ],
  "tire-size": ["#wizTireSize"],
  "type-option": ["#wizardTypeList .wiz-opt", "#wizardCustomType"],
  "variant-option": ["#wizardVariantList .wiz-opt"],
  tireWidth: ["#wizTireWidth"],
  tireAspect: ["#wizTireAspect"],
  rim: ["#wizRim"],
  finalDrive: ["#wizFinalDrive"],
  topGear: ["#wizGearRatio"],
};

const TIRE_FIELDS: Array<{
  field: ManualField;
  id: string;
  labelKey: string;
  placeholder: string;
  min: string;
  step: string;
}> = [
  {
    field: "tireWidth",
    id: "wizTireWidth",
    labelKey: "settings.tire_width",
    placeholder: "225",
    min: "100",
    step: "1",
  },
  {
    field: "tireAspect",
    id: "wizTireAspect",
    labelKey: "settings.tire_aspect",
    placeholder: "45",
    min: "20",
    step: "1",
  },
  {
    field: "rim",
    id: "wizRim",
    labelKey: "settings.rim_size",
    placeholder: "18",
    min: "10",
    step: "0.5",
  },
];

const POWERTRAINS: ReadonlyArray<NonNullable<FuelType>> = ["ICE", "PHEV", "EV"];

/** An EV's single reduction is its final drive; it has no top gear. */
const EV_RATIO_FIELD = {
  field: "finalDrive",
  id: "wizFinalDrive",
  labelKey: "settings.car.reduction_optional",
  helpKey: "settings.car.reduction_help",
} as const;

/** Asks the powertrain where the library does not say (or for a saved car). */
function PowertrainField(props: { value: FuelType; canBeUnknown: boolean }) {
  return (
    <div class="field wizard-spec-field">
      <label htmlFor="wizPowertrain" class="wizard-spec-label">
        <span>{t("settings.car.powertrain")}</span>
      </label>
      <select
        id="wizPowertrain"
        value={props.value ?? ""}
        aria-describedby="wizPowertrainHelp"
        onChange={(event) =>
          selectPowertrain((event.currentTarget.value || null) as FuelType)
        }
      >
        {props.canBeUnknown ? (
          <option value="">{t("settings.car.powertrain.unknown")}</option>
        ) : null}
        {POWERTRAINS.map((fuelType) => (
          <option key={fuelType} value={fuelType}>
            {t(`settings.car.powertrain.${fuelType.toLowerCase()}`)}
          </option>
        ))}
      </select>
      <div id="wizPowertrainHelp" class="subtle wizard-field-help">
        {t("settings.car.powertrain_help")}
      </div>
    </div>
  );
}

const RATIO_FIELDS: Array<{
  field: RatioField;
  id: string;
  labelKey: string;
  helpKey: string;
}> = [
  {
    field: "finalDrive",
    id: "wizFinalDrive",
    labelKey: "settings.car.final_drive_optional",
    helpKey: "settings.car.final_drive_help",
  },
  {
    field: "topGear",
    id: "wizGearRatio",
    labelKey: "settings.car.top_gear_optional",
    helpKey: "settings.car.top_gear_help",
  },
];

interface OptionItem {
  label: string;
  detail: string | null;
  /** Ratio parts with confidence chips, shown instead of `detail`. */
  parts?: RatioPart[];
  selected?: boolean;
  attrs: Record<string, string>;
  onSelect(): void;
}

function Options(props: {
  id: string;
  list?: boolean;
  message?: string | null;
  error?: string | null;
  items: OptionItem[];
}) {
  return (
    <div
      class={
        props.list ? "wizard-options wizard-options--list" : "wizard-options"
      }
      id={props.id}
    >
      {props.message ? <em>{props.message}</em> : null}
      {props.error ? (
        <div class="wizard-load-error" role="alert">
          <strong class="wizard-load-error__title">{props.error}</strong>
          <div class="wizard-load-error__hint">
            {t("settings.wizard.load_failed_hint")}
          </div>
          <div class="wizard-load-error__actions">
            <button
              type="button"
              class="btn btn--primary"
              data-wizard-recovery="retry"
              onClick={() => void loadCurrentStep()}
            >
              {t("settings.wizard.retry")}
            </button>
            <button
              type="button"
              class="btn btn--muted"
              data-wizard-recovery="manual"
              onClick={() => void continueWithManualSpecs()}
            >
              {t("settings.wizard.continue_manual")}
            </button>
          </div>
        </div>
      ) : null}
      {props.items.map((item, index) => (
        <button
          key={`${props.id}-${index}`}
          type="button"
          class="wiz-opt"
          data-selected={item.selected ? "true" : undefined}
          aria-pressed={item.selected ? "true" : "false"}
          onClick={item.onSelect}
          {...item.attrs}
        >
          <span>{item.label}</span>
          {item.parts ? (
            <span class="wiz-opt-detail wiz-opt-parts">
              {item.parts.map((part) => (
                <span key={part.text} class="wiz-opt-part">
                  {part.text} <ProvenanceChip tier={part.tier} />
                </span>
              ))}
            </span>
          ) : item.detail ? (
            <span class="wiz-opt-detail">{item.detail}</span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

function libraryItems<T>(
  options: LibraryOptions<T>,
  toItem: (option: T, index: number) => OptionItem,
): { message: string | null; error: string | null; items: OptionItem[] } {
  return {
    message: options.status === "loading" ? options.message : null,
    error: options.status === "error" ? options.message : null,
    items: options.status === "ready" ? options.options.map(toItem) : [],
  };
}

function CustomEntry(props: {
  kind: "brand" | "type" | "model";
  labelKey: string;
  maxLength: number;
  placeholder: string;
  intro?: ComponentChildren;
}) {
  const id = `wizardCustom${props.kind[0].toUpperCase()}${props.kind.slice(1)}`;
  const input = useRef<HTMLInputElement | null>(null);
  return (
    <div
      class={
        props.intro ? "wizard-custom wizard-custom--branch" : "wizard-custom"
      }
    >
      {props.intro}
      <label for={id}>{t(props.labelKey)}</label>
      <input
        id={id}
        ref={input}
        type="text"
        maxLength={props.maxLength}
        placeholder={props.placeholder}
      />
      <button
        id={`${id}Btn`}
        type="button"
        class="btn btn--primary"
        onClick={() =>
          void submitCustom(props.kind, input.current?.value ?? "")
        }
      >
        {t("settings.car.use_custom")}
      </button>
    </div>
  );
}

function LibraryMissNote() {
  const { brand, carType, libraryMiss } = wizard.value;
  return libraryMiss ? (
    <div class="wizard-info-line" role="status">
      {t("settings.wizard.no_library_data", {
        name: libraryMiss === "brand" ? brand : `${brand} ${carType}`,
      })}
    </div>
  ) : null;
}

function SpecsForm() {
  const state = wizard.value;
  const inputs = manualInputs.value;
  const refs = specProvenance(state, inputs);
  const editing = state.editing;
  const fromLibrary =
    tireOptions.value.length > 0 || gearboxOptions.value.length > 0;
  const fuelType = wizardFuelType(state);
  const ratioFields = fuelType === "EV" ? [EV_RATIO_FIELD] : RATIO_FIELDS;
  return (
    <div class="wizard-branch-card wizard-custom-specs" id="wizardSpecsForm">
      <div class="wizard-branch-card__header">
        <strong class="wizard-branch-label">
          {t("settings.car.specs_title")}
        </strong>
        <div class="subtle wizard-custom-specs__note">
          {t(
            editing
              ? "settings.car.edit_specs_note"
              : fromLibrary
                ? "settings.car.library_specs_note"
                : "settings.car.manual_specs_note",
          )}
        </div>
      </div>
      {asksPowertrain(state) ? (
        <PowertrainField value={fuelType} canBeUnknown={!editing?.fuelType} />
      ) : null}
      <div class="field wizard-spec-field">
        <label htmlFor="wizTireSize" class="wizard-spec-label">
          <span>{t("settings.car.tire_size")}</span>
          <ProvenanceChip tier={provenanceTier(refs.tire)} />
        </label>
        <input
          id="wizTireSize"
          type="text"
          inputMode="text"
          autoComplete="off"
          placeholder={t("settings.car.tire_size_placeholder")}
          value={tireSizeText.value}
          aria-describedby="wizTireSizeHelp"
          onInput={(event) => editTireSize(event.currentTarget.value)}
        />
        <div id="wizTireSizeHelp" class="subtle wizard-field-help">
          {tireSizeUnreadable.value
            ? t("settings.car.tire_size_unreadable")
            : t("settings.car.tire_size_help")}
        </div>
        {editing?.staggeredTire ? (
          <div class="subtle wizard-field-help" data-staggered-note>
            {t("settings.car.staggered_note", {
              sizes: editing.staggeredTire,
            })}
          </div>
        ) : null}
      </div>
      <div class="settings-subgrid wizard-tire-grid">
        {TIRE_FIELDS.map((input) => (
          <div class="field" key={input.field}>
            <label htmlFor={input.id}>{t(input.labelKey)}</label>
            <input
              id={input.id}
              type="number"
              inputMode="decimal"
              placeholder={input.placeholder}
              min={input.min}
              step={input.step}
              value={inputs[input.field]}
              onInput={(event) =>
                editManualInput(input.field, event.currentTarget.value)
              }
            />
          </div>
        ))}
      </div>
      {ratioFields.map((input) => (
        <div class="field wizard-spec-field" key={input.field}>
          <label htmlFor={input.id} class="wizard-spec-label">
            <span>{t(input.labelKey)}</span>
            <ProvenanceChip tier={provenanceTier(refs[input.field])} />
          </label>
          <div class="wizard-ratio-row">
            <input
              id={input.id}
              type="number"
              inputMode="decimal"
              placeholder={t("settings.car.ratio_placeholder")}
              min="0.1"
              step="0.01"
              value={inputs[input.field]}
              aria-describedby={`${input.id}Help`}
              onInput={(event) =>
                editManualInput(input.field, event.currentTarget.value)
              }
            />
            <button
              type="button"
              class="btn btn--muted wizard-unknown-btn"
              data-ratio-unknown={input.field}
              disabled={!inputs[input.field]}
              onClick={() => clearRatio(input.field)}
            >
              {t("settings.car.ratio_dont_know")}
            </button>
          </div>
          <div id={`${input.id}Help`} class="subtle wizard-field-help">
            {t(input.helpKey)}
          </div>
        </div>
      ))}
    </div>
  );
}

function Steps() {
  const current = step.value;
  const state = wizard.value;
  const brands = libraryItems(brandOptions.value, (brand) => ({
    label: brand,
    detail: null,
    attrs: { "data-value": brand },
    onSelect: () => void selectBrand(brand),
  }));
  const types = libraryItems(typeOptions.value, (carType) => ({
    label: carType,
    detail: null,
    attrs: { "data-value": carType },
    onSelect: () => void selectType(carType),
  }));
  const models = libraryItems(modelOptions.value, (model, index) => ({
    label: model.model,
    detail: `${model.tire_width_mm}/${model.tire_aspect_pct}R${model.rim_in}`,
    attrs: { "data-idx": String(index) },
    onSelect: () => void selectModel(index),
  }));
  const tires = tireOptions.value;
  const gearboxes = gearboxOptions.value;
  return (
    <>
      <div id="wizardStep0" class="wizard-step" hidden={current !== 0}>
        <h3>{t("settings.car.step_brand")}</h3>
        <Options id="wizardBrandList" {...brands} />
        <CustomEntry
          kind="brand"
          labelKey="settings.car.or_custom_brand"
          maxLength={32}
          placeholder="e.g. Mercedes-Benz"
        />
      </div>
      <div id="wizardStep1" class="wizard-step" hidden={current !== 1}>
        <h3>{t("settings.car.step_type")}</h3>
        <LibraryMissNote />
        <Options id="wizardTypeList" {...types} />
        <CustomEntry
          kind="type"
          labelKey={
            state.libraryMiss
              ? "settings.car.custom_type"
              : "settings.car.or_custom_type"
          }
          maxLength={32}
          placeholder="e.g. Van"
        />
      </div>
      <div id="wizardStep2" class="wizard-step" hidden={current !== 2}>
        <h3>{t("settings.car.step_model")}</h3>
        <LibraryMissNote />
        <Options id="wizardModelList" list {...models} />
        <CustomEntry
          kind="model"
          labelKey={
            state.libraryMiss
              ? "settings.car.custom_model"
              : "settings.car.or_custom_model"
          }
          maxLength={64}
          placeholder="e.g. C-Class W205"
          intro={
            state.libraryMiss ? null : (
              <>
                <strong class="wizard-branch-label">
                  {t("settings.car.manual_branch_title")}
                </strong>
                <div class="subtle wizard-branch-note">
                  {t("settings.car.manual_model_note")}
                </div>
              </>
            )
          }
        />
      </div>
      <div id="wizardStep3" class="wizard-step" hidden={current !== 3}>
        <h3>{t("settings.car.step_variant")}</h3>
        <div class="subtle wizard-branch-note">
          {t("settings.car.variant_years_note")}
        </div>
        <Options
          id="wizardVariantList"
          list
          items={variantOptions.value.map((variant, index) => ({
            label: variant.name,
            detail: variantDetail(variant),
            attrs: { "data-idx": String(index) },
            onSelect: () => void selectVariant(index),
          }))}
        />
      </div>
      <div id="wizardStep4" class="wizard-step" hidden={current !== SPECS_STEP}>
        {tires.length ? (
          <div class="wizard-library-picks">
            <h3>{t("settings.car.step_wheels")}</h3>
            <Options
              id="wizardTireList"
              items={tires.map((tire, index) => ({
                label: tire.name,
                detail: formatCarLibraryTireOption(tire, fmt),
                selected: tire === state.selectedTire,
                attrs: { "data-tire-idx": String(index) },
                onSelect: () => selectTire(index),
              }))}
            />
          </div>
        ) : null}
        {gearboxes.length || noGearboxesMessage.value ? (
          <div class="wizard-library-picks">
            <h3 class="wizard-section-title">
              {t("settings.car.step_gearbox")}
            </h3>
            <Options
              id="wizardGearboxList"
              list
              message={noGearboxesMessage.value}
              items={gearboxes.map((gearbox, index) => ({
                label: gearbox.name,
                detail: null,
                parts: gearboxParts(gearbox, fmt, t),
                selected: gearbox === state.selectedGearbox,
                attrs: { "data-idx": String(index) },
                onSelect: () => selectGearbox(index),
              }))}
            />
          </div>
        ) : null}
        <SpecsForm />
      </div>
    </>
  );
}

export function CarWizard() {
  const open = isOpen.value;
  const state = wizard.value;
  const inputs = manualInputs.value;
  const current = state.step;
  const editing = state.editing;
  const card = useRef<HTMLDivElement | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(open);
  const request = focusRequest.value;

  useLayoutEffect(() => {
    if (open && !wasOpen.current) {
      const active = document.activeElement;
      returnFocus.current =
        active instanceof HTMLElement && active !== document.body
          ? active
          : null;
      if (card.current) {
        card.current.scrollTop = 0;
      }
    }
    if (!open && wasOpen.current) {
      const target = returnFocus.current?.isConnected
        ? returnFocus.current
        : document.getElementById("addCarBtn");
      returnFocus.current = null;
      target?.focus();
    }
    wasOpen.current = open;
  }, [open]);

  // A request made while Settings is still opening waits until it is visible.
  const appliedFocus = useRef(0);
  const viewVisible = activeView.value === "settingsView";
  useLayoutEffect(() => {
    if (!request || request.seq === appliedFocus.current || !card.current) {
      return;
    }
    for (const selector of FOCUS_SELECTORS[request.target]) {
      const element = card.current.querySelector<HTMLElement>(selector);
      if (element?.offsetParent) {
        element.focus();
        appliedFocus.current = request.seq;
        return;
      }
    }
  }, [request, viewVisible]);

  const view = summary(state, inputs, fmt, t);
  const capabilities =
    current === SPECS_STEP
      ? carCapabilities(specProvenance(state, inputs), wizardFuelType(state))
      : null;
  return (
    <div class="wizard-modal-layer" hidden={!open}>
      {/* biome-ignore lint/a11y/noStaticElementInteractions: clicking outside closes the dialog; Escape and the close button are the keyboard paths. */}
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: see above. */}
      <div
        id="wizardBackdrop"
        class="wizard-backdrop"
        hidden={!open}
        onClick={closeWizard}
      />
      <div
        id="addCarWizard"
        class="panel card add-car-wizard"
        hidden={!open}
        role="dialog"
        aria-modal="true"
        aria-labelledby="wizardTitle"
        data-mode={editing ? "edit" : "add"}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            closeWizard();
          }
        }}
        ref={card}
      >
        <div class="wizard-header">
          <div class="wizard-header__text">
            <strong id="wizardTitle">
              {editing
                ? t("settings.car.edit_title", { name: editing.name })
                : t("settings.car.add_title")}
            </strong>
            <div class="subtle">
              {t(
                editing
                  ? "settings.car.edit_intro"
                  : "settings.car.wizard_intro",
              )}
            </div>
            {editing ? null : (
              <div id="wizardProgressText" class="wizard-progress-text">
                {progressText(current, t)}
              </div>
            )}
          </div>
          <button
            id="wizardCloseBtn"
            type="button"
            class="btn btn--muted wizard-close"
            aria-label="Close wizard"
            onClick={closeWizard}
          >
            {"×"}
          </button>
        </div>
        <div class="wizard-shell">
          <div class="wizard-main">
            <div class="wizard-steps">
              <div class="wizard-step-indicators" hidden={Boolean(editing)}>
                {STEP_LABEL_KEYS.map((key, index) => (
                  <span
                    key={key}
                    class="wizard-step-dot"
                    data-step={String(index)}
                    data-step-state={
                      index === current
                        ? "active"
                        : index < current
                          ? "done"
                          : "upcoming"
                    }
                    aria-current={index === current ? "step" : undefined}
                  >
                    <span class="wizard-step-dot__number">{index + 1}</span>
                    <span class="wizard-step-dot__label">{t(key)}</span>
                  </span>
                ))}
              </div>
              <Steps />
            </div>
            <div class="wizard-nav">
              <div
                id="wizardActionHint"
                class="subtle wizard-nav__status"
                aria-live="polite"
              >
                {actionHint(state, inputs, gearboxOptions.value.length, t)}
              </div>
              <div class="wizard-nav__actions">
                <button
                  id="wizardBackBtn"
                  type="button"
                  class="btn btn--muted"
                  hidden={current === 0 || Boolean(editing)}
                  onClick={() => void goBack()}
                >
                  {t("settings.car.back")}
                </button>
                <button
                  id="wizardManualAddBtn"
                  type="button"
                  class="btn btn--success"
                  hidden={current !== SPECS_STEP}
                  disabled={
                    !(current === SPECS_STEP && canFinish(state, inputs))
                  }
                  onClick={() => void finishWizard()}
                >
                  {t(
                    editing
                      ? "settings.car.finish_save"
                      : "settings.car.finish_add",
                  )}
                </button>
              </div>
            </div>
          </div>
          <aside
            class={
              capabilities
                ? "wizard-summary-card wizard-summary-card--capabilities"
                : "wizard-summary-card"
            }
            aria-live="polite"
          >
            {capabilities ? (
              <section
                class="wizard-capabilities"
                aria-labelledby="wizardCapabilitiesTitle"
              >
                <div
                  id="wizardCapabilitiesTitle"
                  class="wizard-summary-card__title"
                >
                  {t("capabilities.car_title")}
                </div>
                <CapabilityList
                  id="wizardCapabilities"
                  capabilities={capabilities}
                  fuelType={wizardFuelType(state)}
                />
                <div class="subtle wizard-capabilities__obd">
                  {t(
                    wizardFuelType(state) === "EV"
                      ? "capabilities.obd_hint_ev"
                      : "capabilities.obd_hint",
                  )}
                </div>
              </section>
            ) : (
              <div class="wizard-task-callout">
                <strong>{t("settings.car.wizard_task_title")}</strong>
                <div class="subtle">{t("settings.car.wizard_task_intro")}</div>
              </div>
            )}
            <div class="wizard-summary-card__title">
              {t("settings.car.wizard_summary_title")}
            </div>
            <div class="subtle">{t("settings.car.wizard_summary_intro")}</div>
            <div id="wizardSummaryPanel">
              <div class="wizard-summary-preview">
                <div class="wizard-summary-preview__label">
                  {t("settings.car.wizard_summary_name")}
                </div>
                <div class="wizard-summary-preview__value">
                  {view.profileName}
                </div>
              </div>
              <dl class="wizard-summary-list">
                {view.rows.map((row) => (
                  <div key={row.label} class="wizard-summary-item">
                    <dt>{row.label}</dt>
                    <dd>{row.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
