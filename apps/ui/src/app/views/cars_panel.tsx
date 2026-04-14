import type { CarSelectionState } from "../car_selection_state";
import type { UiCarsDom } from "../dom/cars_dom";
import { createUiPreactMount } from "../runtime/ui_preact_mount";
import type { CarRecord } from "../../transport/http_models";
import {
  bindCarsFeatureInteractions,
  type CarsFeatureInteractionHandlers,
} from "./cars_feature_bindings";
import type { ViewDisposer } from "./dom_event_bindings";
import { renderInlineStatePanel } from "./dom_helpers";
import {
  bindSettingsCarListActions,
  renderSettingsCarList,
  type SettingsCarListAction,
} from "./settings_car_list_view";

export interface CarsListHighlightedFeedback {
  carId: string;
  carName: string;
}

export interface CarsListRenderModel {
  activeCarId: string | null;
  carSelectionState: CarSelectionState;
  cars: readonly CarRecord[];
  highlightedCarFeedback: CarsListHighlightedFeedback | null;
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
  fmt: (value: number, digits?: number) => string;
}

export interface CarsListPanelView {
  bindActions(handlers: { onAction(action: SettingsCarListAction): void }): void;
  render(model: CarsListRenderModel): void;
}

export interface CarsWizardPanelBridge {
  readonly dom: UiCarsDom;
  bindActions(handlers: CarsFeatureInteractionHandlers): void;
}

export interface CarsPanelView {
  readonly list: CarsListPanelView;
  readonly wizard: CarsWizardPanelBridge;
}

function CarsPanel() {
  return (
    <>
      <div class="panel card">
        <div class="car-tab-header">
          <strong data-i18n="settings.car.manage">Manage Cars</strong>
          <button id="addCarBtn" class="btn btn--success" data-i18n="settings.car.add_new">
            + Add Car
          </button>
        </div>
        <div class="subtle" data-i18n="settings.car.hint">
          Add cars from the library or enter specs manually. Activate a car to use it for
          analysis.
        </div>
        <div id="carSelectionGuidance" class="empty-state empty-state--inline" hidden />
        <div class="settings-table-wrap">
          <table class="car-list-table settings-entity-table settings-entity-table--cars">
            <thead>
              <tr>
                <th data-i18n="settings.car.col_name">Name</th>
                <th data-i18n="settings.car.col_setup">Setup</th>
                <th data-i18n="settings.car.col_actions">Actions</th>
              </tr>
            </thead>
            <tbody id="carListBody">
              <tr>
                <td colSpan={3} data-i18n="settings.car.no_cars">
                  No cars added yet.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div id="wizardBackdrop" class="wizard-backdrop" hidden />
      <div
        id="addCarWizard"
        class="panel card add-car-wizard"
        hidden
        role="dialog"
        aria-modal="true"
        aria-labelledby="wizardTitle"
      >
        <div class="wizard-header">
          <div class="wizard-header__text">
            <strong id="wizardTitle" data-i18n="settings.car.add_title">
              Add a Car
            </strong>
            <div class="subtle" data-i18n="settings.car.wizard_intro">
              Use the library when it fits, or branch into manual specs without losing your place.
            </div>
            <div id="wizardProgressText" class="wizard-progress-text">
              Step 1 of 5 · Brand
            </div>
          </div>
          <button id="wizardCloseBtn" class="btn btn--muted wizard-close" aria-label="Close wizard">
            {"\u00d7"}
          </button>
        </div>
        <div class="wizard-shell">
          <div class="wizard-main">
            <div class="wizard-steps">
              <div class="wizard-step-indicators" aria-label="Add car progress">
                <span class="wizard-step-dot active" data-step="0">
                  <span class="wizard-step-dot__number">1</span>
                  <span class="wizard-step-dot__label" data-i18n="settings.car.step_brand_short">
                    Brand
                  </span>
                </span>
                <span class="wizard-step-dot" data-step="1">
                  <span class="wizard-step-dot__number">2</span>
                  <span class="wizard-step-dot__label" data-i18n="settings.car.step_type_short">
                    Type
                  </span>
                </span>
                <span class="wizard-step-dot" data-step="2">
                  <span class="wizard-step-dot__number">3</span>
                  <span class="wizard-step-dot__label" data-i18n="settings.car.step_model_short">
                    Model
                  </span>
                </span>
                <span class="wizard-step-dot" data-step="3">
                  <span class="wizard-step-dot__number">4</span>
                  <span class="wizard-step-dot__label" data-i18n="settings.car.step_variant_short">
                    Variant
                  </span>
                </span>
                <span class="wizard-step-dot" data-step="4">
                  <span class="wizard-step-dot__number">5</span>
                  <span class="wizard-step-dot__label" data-i18n="settings.car.step_specs_short">
                    Specs
                  </span>
                </span>
              </div>

              <div id="wizardStep0" class="wizard-step active">
                <h3 data-i18n="settings.car.step_brand">Select Brand</h3>
                <div class="wizard-options" id="wizardBrandList" />
                <div class="wizard-custom">
                  <label data-i18n="settings.car.or_custom_brand">Or type a custom brand:</label>
                  <input
                    id="wizardCustomBrand"
                    type="text"
                    maxLength={32}
                    placeholder="e.g. Mercedes-Benz"
                  />
                  <button
                    id="wizardCustomBrandBtn"
                    class="btn btn--primary"
                    data-i18n="settings.car.use_custom"
                  >
                    Use Custom
                  </button>
                </div>
              </div>

              <div id="wizardStep1" class="wizard-step">
                <h3 data-i18n="settings.car.step_type">Select Type</h3>
                <div class="wizard-options" id="wizardTypeList" />
                <div class="wizard-custom">
                  <label data-i18n="settings.car.or_custom_type">Or type a custom type:</label>
                  <input id="wizardCustomType" type="text" maxLength={32} placeholder="e.g. Van" />
                  <button
                    id="wizardCustomTypeBtn"
                    class="btn btn--primary"
                    data-i18n="settings.car.use_custom"
                  >
                    Use Custom
                  </button>
                </div>
              </div>

              <div id="wizardStep2" class="wizard-step">
                <h3 data-i18n="settings.car.step_model">Select Model</h3>
                <div class="wizard-options wizard-options--list" id="wizardModelList" />
                <div class="wizard-custom wizard-custom--branch">
                  <strong class="wizard-branch-label" data-i18n="settings.car.manual_branch_title">
                    Manual specs branch
                  </strong>
                  <div class="subtle wizard-branch-note" data-i18n="settings.car.manual_model_note">
                    Skip library variants and finish with your own wheel and gearbox values.
                  </div>
                  <label data-i18n="settings.car.or_custom_model">Or type a custom model:</label>
                  <input
                    id="wizardCustomModel"
                    type="text"
                    maxLength={64}
                    placeholder="e.g. C-Class W205"
                  />
                  <button
                    id="wizardCustomModelBtn"
                    class="btn btn--primary"
                    data-i18n="settings.car.use_custom"
                  >
                    Use Custom
                  </button>
                </div>
              </div>

              <div id="wizardStep3" class="wizard-step">
                <h3 data-i18n="settings.car.step_variant">Select Variant</h3>
                <div class="wizard-options wizard-options--list" id="wizardVariantList" />
              </div>

              <div id="wizardStep4" class="wizard-step">
                <div class="wizard-branch-card wizard-branch-card--library">
                  <div class="wizard-branch-card__header">
                    <strong class="wizard-branch-label" data-i18n="settings.car.library_branch_title">
                      Library-matched specs
                    </strong>
                    <div class="subtle wizard-branch-note" data-i18n="settings.car.library_branch_note">
                      Choose the tire and gearbox that match this car. Finish stays pinned below.
                    </div>
                  </div>
                  <h3 data-i18n="settings.car.step_wheels">Select Wheels</h3>
                  <div class="wizard-options" id="wizardTireList" />
                  <h3 data-i18n="settings.car.step_gearbox" class="wizard-section-title">
                    Select Gearbox
                  </h3>
                  <div class="wizard-options wizard-options--list" id="wizardGearboxList" />
                </div>
                <div class="wizard-branch-divider">
                  <span data-i18n="settings.car.branch_divider">Or switch to the manual branch</span>
                </div>
                <div class="wizard-branch-card wizard-branch-card--manual wizard-custom-specs">
                  <div class="wizard-branch-card__header">
                    <strong class="wizard-branch-label" data-i18n="settings.car.manual_branch_title">
                      Manual specs branch
                    </strong>
                    <div
                      class="subtle wizard-custom-specs__note"
                      data-i18n="settings.car.manual_specs_note"
                    >
                      Use this branch when the library stops short or you already know the wheel and
                      gearbox measurements.
                    </div>
                  </div>
                  <div class="settings-subgrid">
                    <div class="field">
                      <label htmlFor="wizTireWidth" data-i18n="settings.tire_width">
                        Tire Width (mm)
                      </label>
                      <input id="wizTireWidth" type="number" min="100" step="1" defaultValue="225" />
                    </div>
                    <div class="field">
                      <label htmlFor="wizTireAspect" data-i18n="settings.tire_aspect">
                        Tire Aspect (%)
                      </label>
                      <input id="wizTireAspect" type="number" min="20" step="1" defaultValue="45" />
                    </div>
                    <div class="field">
                      <label htmlFor="wizRim" data-i18n="settings.rim_size">
                        Rim Size (in)
                      </label>
                      <input id="wizRim" type="number" min="10" step="0.5" defaultValue="18" />
                    </div>
                    <div class="field">
                      <label htmlFor="wizFinalDrive" data-i18n="settings.final_drive_ratio">
                        Final Drive Ratio
                      </label>
                      <input
                        id="wizFinalDrive"
                        type="number"
                        step="0.01"
                        min="0.1"
                        defaultValue="3.08"
                      />
                    </div>
                    <div class="field">
                      <label htmlFor="wizGearRatio" data-i18n="settings.top_gear_ratio">
                        Top Gear Ratio
                      </label>
                      <input
                        id="wizGearRatio"
                        type="number"
                        step="0.01"
                        min="0.1"
                        defaultValue="0.64"
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div class="wizard-nav">
              <div id="wizardActionHint" class="subtle wizard-nav__status" aria-live="polite" />
              <div class="wizard-nav__actions">
                <button id="wizardBackBtn" class="btn btn--muted" data-i18n="settings.car.back">
                  Back
                </button>
                <button
                  id="wizardManualAddBtn"
                  class="btn btn--success"
                  hidden
                  data-i18n="settings.car.finish_add"
                >
                  Add Car
                </button>
              </div>
            </div>
          </div>

          <aside class="wizard-summary-card" aria-live="polite">
            <div class="wizard-task-callout">
              <strong data-i18n="settings.car.wizard_task_title">Guided setup</strong>
              <div class="subtle" data-i18n="settings.car.wizard_task_intro">
                This flow pauses the rest of Settings so you can build the next analysis profile step
                by step without losing your place.
              </div>
            </div>
            <div class="wizard-summary-card__title" data-i18n="settings.car.wizard_summary_title">
              Current selection
            </div>
            <div class="subtle" data-i18n="settings.car.wizard_summary_intro">
              Your choices stay visible here while the profile comes together.
            </div>
            <div id="wizardSummaryPanel" />
          </aside>
        </div>
      </div>
    </>
  );
}

function queryInHost<T extends HTMLElement>(host: HTMLElement, selector: string): T | null {
  return host.querySelector<T>(selector);
}

function requireInHost<T extends HTMLElement>(host: HTMLElement, selector: string): T {
  const element = queryInHost<T>(host, selector);
  if (!element) {
    throw new Error(`Cars feature requires ${selector}`);
  }
  return element;
}

function createCarsPanelDom(host: HTMLElement): UiCarsDom {
  return {
    addCarBtn: requireInHost<HTMLButtonElement>(host, "#addCarBtn"),
    wizardBackdrop: queryInHost<HTMLElement>(host, "#wizardBackdrop"),
    addCarWizard: requireInHost<HTMLElement>(host, "#addCarWizard"),
    wizardProgressText: queryInHost<HTMLElement>(host, "#wizardProgressText"),
    wizardCloseBtn: queryInHost<HTMLButtonElement>(host, "#wizardCloseBtn"),
    wizardBackBtn: queryInHost<HTMLButtonElement>(host, "#wizardBackBtn"),
    wizardSteps: [0, 1, 2, 3, 4].map((index) =>
      queryInHost<HTMLElement>(host, `#wizardStep${index}`)
    ),
    wizardStepDots: Array.from(host.querySelectorAll<HTMLElement>(".wizard-step-dot")),
    wizardSummaryPanel: queryInHost<HTMLElement>(host, "#wizardSummaryPanel"),
    wizardActionHint: queryInHost<HTMLElement>(host, "#wizardActionHint"),
    wizardBrandList: queryInHost<HTMLElement>(host, "#wizardBrandList"),
    wizardTypeList: queryInHost<HTMLElement>(host, "#wizardTypeList"),
    wizardModelList: queryInHost<HTMLElement>(host, "#wizardModelList"),
    wizardVariantList: queryInHost<HTMLElement>(host, "#wizardVariantList"),
    wizardTireList: queryInHost<HTMLElement>(host, "#wizardTireList"),
    wizardGearboxList: queryInHost<HTMLElement>(host, "#wizardGearboxList"),
    wizardCustomBrandInput: queryInHost<HTMLInputElement>(host, "#wizardCustomBrand"),
    wizardCustomBrandBtn: queryInHost<HTMLButtonElement>(host, "#wizardCustomBrandBtn"),
    wizardCustomTypeInput: queryInHost<HTMLInputElement>(host, "#wizardCustomType"),
    wizardCustomTypeBtn: queryInHost<HTMLButtonElement>(host, "#wizardCustomTypeBtn"),
    wizardCustomModelInput: queryInHost<HTMLInputElement>(host, "#wizardCustomModel"),
    wizardCustomModelBtn: queryInHost<HTMLButtonElement>(host, "#wizardCustomModelBtn"),
    wizardManualAddBtn: queryInHost<HTMLButtonElement>(host, "#wizardManualAddBtn"),
    wizTireWidthInput: queryInHost<HTMLInputElement>(host, "#wizTireWidth"),
    wizTireAspectInput: queryInHost<HTMLInputElement>(host, "#wizTireAspect"),
    wizRimInput: queryInHost<HTMLInputElement>(host, "#wizRim"),
    wizFinalDriveInput: queryInHost<HTMLInputElement>(host, "#wizFinalDrive"),
    wizGearRatioInput: queryInHost<HTMLInputElement>(host, "#wizGearRatio"),
  };
}

function renderCreationFeedback(
  feedback: CarsListHighlightedFeedback,
  deps: Pick<CarsListRenderModel, "escapeHtml" | "t">,
): string {
  return `
    <div class="empty-state empty-state--inline car-selection-feedback car-selection-feedback--success" role="status">
      <strong class="empty-state__title">${deps.escapeHtml(deps.t("settings.car.created_title"))}</strong>
      <span class="empty-state__body">${deps.escapeHtml(
        deps.t("settings.car.created_body", { name: feedback.carName }),
      )}</span>
      <span class="empty-state__detail">${deps.escapeHtml(deps.t("settings.car.created_detail"))}</span>
    </div>
  `;
}

function renderCarsGuidance(target: HTMLElement | null, model: CarsListRenderModel): void {
  if (!target) {
    return;
  }
  if (
    model.carSelectionState.kind === "loading"
    || model.carSelectionState.kind === "no_cars"
  ) {
    target.hidden = true;
    target.replaceChildren();
    return;
  }
  if (model.carSelectionState.kind === "active" && model.highlightedCarFeedback) {
    target.hidden = false;
    target.innerHTML = renderCreationFeedback(model.highlightedCarFeedback, model);
    return;
  }
  if (model.carSelectionState.kind === "active") {
    target.hidden = true;
    target.replaceChildren();
    return;
  }
  target.hidden = false;
  target.innerHTML = renderInlineStatePanel({
    titleHtml: model.escapeHtml(model.t("settings.car.guidance.no_active_title")),
    bodyHtml: model.escapeHtml(model.t("settings.car.guidance.no_active")),
    detailHtml: model.escapeHtml(model.t("settings.car.guidance.no_active_detail")),
  });
}

export function mountCarsPanel(host: HTMLElement): CarsPanelView {
  const mount = createUiPreactMount(host);
  mount.render(<CarsPanel />);

  const dom = createCarsPanelDom(host);
  const carSelectionGuidance = requireInHost<HTMLElement>(host, "#carSelectionGuidance");
  const carListBody = requireInHost<HTMLElement>(host, "#carListBody");
  let listDisposer: ViewDisposer | null = null;
  let wizardDisposer: ViewDisposer | null = null;

  return {
    list: {
      bindActions(handlers): void {
        listDisposer?.();
        listDisposer = bindSettingsCarListActions({ carListBody }, handlers);
      },
      render(model): void {
        renderCarsGuidance(carSelectionGuidance, model);
        if (model.carSelectionState.kind === "loading") {
          return;
        }
        renderSettingsCarList(carListBody, {
          activeCarId: model.activeCarId,
          cars: [...model.cars],
          highlightedCarId: model.highlightedCarFeedback?.carId ?? null,
          t: model.t,
          escapeHtml: model.escapeHtml,
          fmt: model.fmt,
        });
      },
    },
    wizard: {
      dom,
      bindActions(handlers): void {
        wizardDisposer?.();
        wizardDisposer = bindCarsFeatureInteractions(dom, handlers);
      },
    },
  };
}
