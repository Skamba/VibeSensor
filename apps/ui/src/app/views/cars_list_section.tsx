import { memo } from "preact/compat";
import { getUiText as t } from "../ui_i18n";
import { inlineStateActionClass } from "./inline_state_panel_models";
import type {
  CarsInlineStateViewModel,
  CarsListAction,
  CarsListRowViewModel,
  SettingsCarListTableRenderModel,
} from "./settings_car_list_view";

export interface CarsListRenderModel {
  guidance: CarsInlineStateViewModel | null;
  table: SettingsCarListTableRenderModel | null;
}

export type CarsListPanelActionHandlers = {
  onAction(action: CarsListAction): void;
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

const CarsTableRow = memo(function CarsTableRow(props: {
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
});

function CarsTableBody(props: {
  actions: CarsListPanelActionHandlers | null;
  table: SettingsCarListTableRenderModel | null;
}) {
  const { actions, table } = props;
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

export function CarsListSection(props: {
  actions: CarsListPanelActionHandlers | null;
  addCarButtonRef: { current: HTMLButtonElement | null };
  model: CarsListRenderModel;
  onOpenWizard(): void;
}) {
  const { actions, addCarButtonRef, model, onOpenWizard } = props;
  return (
    <div class="panel card">
      <div class="car-tab-header">
        <strong>
          {t("settings.car.manage", "Manage Cars")}
        </strong>
        <button
          id="addCarBtn"
          class="btn btn--success"
          onClick={onOpenWizard}
          ref={addCarButtonRef}
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
          <CarsInlineStatePanel actions={actions} state={model.guidance} />
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
            <CarsTableBody actions={actions} table={model.table} />
          </tbody>
        </table>
      </div>
    </div>
  );
}
