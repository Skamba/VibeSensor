import type { UiCarsDom } from "../dom/cars_dom";
import { createUiPreactMount } from "../runtime/ui_preact_mount";
import {
  bindCarsFeatureInteractions,
  type CarsFeatureInteractionHandlers,
} from "./cars_feature_bindings";
import type { ViewDisposer } from "./dom_event_bindings";
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

type CarsListPanelActionHandlers = {
  onAction(action: CarsListAction): void;
};

type CarsPanelBridgeState = {
  actions: CarsListPanelActionHandlers | null;
  model: CarsListRenderModel;
};

const DEFAULT_CARS_PANEL_MODEL: CarsListRenderModel = {
  guidance: null,
  table: null,
};

function handleCarsListAction(
  actions: CarsListPanelActionHandlers | null,
  action: CarsListAction,
): void {
  actions?.onAction(action);
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
  if (table === null) {
    return (
      <tr>
        <td colSpan={3} data-i18n="settings.car.no_cars">
          No cars added yet.
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

function CarsPanel(props: { state: CarsPanelBridgeState }) {
  const { state } = props;
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
        <div id="carSelectionGuidance" hidden={state.model.guidance === null}>
          {state.model.guidance ? (
            <CarsInlineStatePanel actions={state.actions} state={state.model.guidance} />
          ) : null}
        </div>
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
              <CarsTableBody actions={state.actions} table={state.model.table} />
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

export function mountCarsPanel(host: HTMLElement): CarsPanelView {
  const bridgeState: CarsPanelBridgeState = {
    actions: null,
    model: DEFAULT_CARS_PANEL_MODEL,
  };
  const mount = createUiPreactMount(host);
  const render = () => mount.render(<CarsPanel state={bridgeState} />);
  render();

  const dom = createCarsPanelDom(host);
  let wizardDisposer: ViewDisposer | null = null;

  return {
    list: {
      bindActions(handlers): void {
        bridgeState.actions = handlers;
        render();
      },
      render(model): void {
        bridgeState.model = model;
        render();
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
