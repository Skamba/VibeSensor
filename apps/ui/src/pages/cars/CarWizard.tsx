import type { ComponentChildren } from "preact";
import { useLayoutEffect, useRef } from "preact/hooks";

import { activeView } from "../../app_store";
import { fmt } from "../../format";
import { t } from "../../i18n";
import { formatCarLibraryTireOption } from "./tires";
import {
  actionHint,
  canFinish,
  gearboxDetail,
  MANUAL_INPUT_EXAMPLES,
  type ManualField,
  progressText,
  SPECS_STEP,
  STEP_LABEL_KEYS,
  specBranch,
  summary,
  variantDetail,
} from "./wizard_model";
import {
  brandOptions,
  closeWizard,
  continueWithManualSpecs,
  editManualInput,
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
  selectTire,
  selectType,
  selectVariant,
  step,
  submitCustom,
  tireOptions,
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
    "#wizTireWidth",
  ],
  "type-option": ["#wizardTypeList .wiz-opt", "#wizardCustomType"],
  "variant-option": ["#wizardVariantList .wiz-opt"],
  tireWidth: ["#wizTireWidth"],
  tireAspect: ["#wizTireAspect"],
  rim: ["#wizRim"],
  finalDrive: ["#wizFinalDrive"],
  topGear: ["#wizGearRatio"],
};

const MANUAL_FIELDS: Array<{
  field: ManualField;
  id: string;
  labelKey: string;
  min: string;
  step: string;
}> = [
  {
    field: "tireWidth",
    id: "wizTireWidth",
    labelKey: "settings.tire_width",
    min: "100",
    step: "1",
  },
  {
    field: "tireAspect",
    id: "wizTireAspect",
    labelKey: "settings.tire_aspect",
    min: "20",
    step: "1",
  },
  {
    field: "rim",
    id: "wizRim",
    labelKey: "settings.rim_size",
    min: "10",
    step: "0.5",
  },
  {
    field: "finalDrive",
    id: "wizFinalDrive",
    labelKey: "settings.final_drive_ratio",
    min: "0.1",
    step: "0.01",
  },
  {
    field: "topGear",
    id: "wizGearRatio",
    labelKey: "settings.top_gear_ratio",
    min: "0.1",
    step: "0.01",
  },
];

interface OptionItem {
  label: string;
  detail: string | null;
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
          {item.detail ? (
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
  const inputs = manualInputs.value;
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
        <Options id="wizardTypeList" {...types} />
        <CustomEntry
          kind="type"
          labelKey="settings.car.or_custom_type"
          maxLength={32}
          placeholder="e.g. Van"
        />
      </div>
      <div id="wizardStep2" class="wizard-step" hidden={current !== 2}>
        <h3>{t("settings.car.step_model")}</h3>
        <Options id="wizardModelList" list {...models} />
        <CustomEntry
          kind="model"
          labelKey="settings.car.or_custom_model"
          maxLength={64}
          placeholder="e.g. C-Class W205"
          intro={
            <>
              <strong class="wizard-branch-label">
                {t("settings.car.manual_branch_title")}
              </strong>
              <div class="subtle wizard-branch-note">
                {t("settings.car.manual_model_note")}
              </div>
            </>
          }
        />
      </div>
      <div id="wizardStep3" class="wizard-step" hidden={current !== 3}>
        <h3>{t("settings.car.step_variant")}</h3>
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
        <div class="wizard-branch-card wizard-branch-card--library">
          <div class="wizard-branch-card__header">
            <strong class="wizard-branch-label">
              {t("settings.car.library_branch_title")}
            </strong>
            <div class="subtle wizard-branch-note">
              {t("settings.car.library_branch_note")}
            </div>
          </div>
          <h3>{t("settings.car.step_wheels")}</h3>
          <Options
            id="wizardTireList"
            items={tireOptions.value.map((tire, index) => ({
              label: tire.name,
              detail: formatCarLibraryTireOption(tire, fmt),
              selected: tire === state.selectedTire,
              attrs: { "data-tire-idx": String(index) },
              onSelect: () => selectTire(index),
            }))}
          />
          <h3 class="wizard-section-title">{t("settings.car.step_gearbox")}</h3>
          <Options
            id="wizardGearboxList"
            list
            message={noGearboxesMessage.value}
            items={
              noGearboxesMessage.value
                ? []
                : gearboxOptions.value.map((gearbox, index) => ({
                    label: gearbox.name,
                    detail: gearboxDetail(gearbox, fmt, t),
                    selected: gearbox === state.selectedGearbox,
                    attrs: { "data-idx": String(index) },
                    onSelect: () => selectGearbox(index),
                  }))
            }
          />
        </div>
        <div class="wizard-branch-divider">
          <span>{t("settings.car.branch_divider")}</span>
        </div>
        <div class="wizard-branch-card wizard-branch-card--manual wizard-custom-specs">
          <div class="wizard-branch-card__header">
            <strong class="wizard-branch-label">
              {t("settings.car.manual_branch_title")}
            </strong>
            <div class="subtle wizard-custom-specs__note">
              {t("settings.car.manual_specs_note")}
            </div>
          </div>
          <div class="settings-subgrid">
            {MANUAL_FIELDS.map((input) => (
              <div class="field" key={input.field}>
                <label htmlFor={input.id}>{t(input.labelKey)}</label>
                <input
                  id={input.id}
                  type="number"
                  placeholder={MANUAL_INPUT_EXAMPLES[input.field]}
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
        </div>
      </div>
    </>
  );
}

export function CarWizard() {
  const open = isOpen.value;
  const state = wizard.value;
  const inputs = manualInputs.value;
  const current = state.step;
  const branch = specBranch(state);
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
        data-spec-branch={
          current === SPECS_STEP ? (branch ?? "pending") : undefined
        }
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
            <strong id="wizardTitle">{t("settings.car.add_title")}</strong>
            <div class="subtle">{t("settings.car.wizard_intro")}</div>
            <div id="wizardProgressText" class="wizard-progress-text">
              {progressText(current, t)}
            </div>
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
              <div class="wizard-step-indicators">
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
                {actionHint(state, inputs, t)}
              </div>
              <div class="wizard-nav__actions">
                <button
                  id="wizardBackBtn"
                  type="button"
                  class="btn btn--muted"
                  hidden={current === 0}
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
                  {t("settings.car.finish_add")}
                </button>
              </div>
            </div>
          </div>
          <aside class="wizard-summary-card" aria-live="polite">
            <div class="wizard-task-callout">
              <strong>{t("settings.car.wizard_task_title")}</strong>
              <div class="subtle">{t("settings.car.wizard_task_intro")}</div>
            </div>
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
