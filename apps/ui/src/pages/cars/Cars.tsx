import { fmt } from "../../format";
import { t } from "../../i18n";
import { carSelection, carSettings } from "../../settings_store";
import { CarWizard } from "./CarWizard";
import { carRows, guidance, type InlineState } from "./car_list_model";
import { activateCar, completeCar, deleteCar, highlighted } from "./cars_store";
import { openWizard } from "./wizard_store";

function InlineStatePanel(props: {
  state: InlineState;
  action?: { label: string; onClick(): void };
}) {
  const { state, action } = props;
  const success = state.tone === "success";
  return (
    <div
      class={
        success
          ? "empty-state empty-state--inline car-selection-feedback car-selection-feedback--success"
          : "empty-state empty-state--inline empty-state--actionable"
      }
      role={success ? "status" : undefined}
    >
      <strong class="empty-state__title">{state.title}</strong>
      <span class="empty-state__body">{state.body}</span>
      {state.detail ? (
        <span class="empty-state__detail">{state.detail}</span>
      ) : null}
      {action ? (
        <div class="empty-state__actions">
          <button
            type="button"
            class="btn btn--success"
            data-inline-state-action="add-car"
            onClick={action.onClick}
          >
            {action.label}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function CarTableBody() {
  const selection = carSelection.value;
  if (selection.kind === "loading") {
    return (
      <tr>
        <td colSpan={3}>{t("settings.car.no_cars")}</td>
      </tr>
    );
  }
  const cars = carSettings.cars.value;
  if (cars.length === 0) {
    return (
      <tr>
        <td colSpan={3}>
          <div class="settings-table-empty-state">
            <InlineStatePanel
              state={{
                title: t("settings.car.empty.title"),
                body: t("settings.car.empty.body"),
                detail: t("settings.car.empty.detail"),
                tone: "default",
              }}
              action={{
                label: t("settings.car.empty.action"),
                onClick: () => void openWizard(),
              }}
            />
          </div>
        </td>
      </tr>
    );
  }
  const rows = carRows(
    cars,
    carSettings.activeCarId.value,
    highlighted.value?.carId ?? null,
    fmt,
    t,
  );
  return (
    <>
      {rows.map((row) => (
        <tr
          key={row.carId}
          class={row.isHighlighted ? "car-list-row--highlighted" : undefined}
          data-car-id={row.carId}
          data-car-complete={row.isComplete ? "true" : "false"}
          data-highlighted={row.isHighlighted ? "true" : "false"}
        >
          <td>
            <div class="car-row__identity">
              <div class="car-row__heading">
                <strong>{row.name}</strong>
              </div>
              {row.type || row.variant ? (
                <div class="car-row__meta">
                  {row.type ? (
                    <span class="car-row__type">{row.type}</span>
                  ) : null}
                  {row.variant ? (
                    <span class="car-row__variant">{row.variant}</span>
                  ) : null}
                </div>
              ) : null}
              <div class="car-status-stack">
                <span
                  class="car-active-pill settings-entity-status"
                  data-state={row.isActive ? "active" : "inactive"}
                >
                  {row.activeText}
                </span>
                <span
                  class="car-readiness-pill settings-entity-status"
                  data-state={row.isComplete ? "ready" : "incomplete"}
                >
                  {row.readinessText}
                </span>
                {row.isHighlighted ? (
                  <span class="car-created-pill settings-entity-status">
                    {t("settings.car.just_added")}
                  </span>
                ) : null}
              </div>
              {row.detail ? (
                <span class="subtle car-row__detail">{row.detail}</span>
              ) : null}
            </div>
          </td>
          <td>
            <div class="car-row__setup">
              {row.metrics.map((metric) => (
                <div key={metric.label} class="car-row__setup-item">
                  <span class="car-row__setup-label">{metric.label}</span>
                  <span class="car-row__setup-value">
                    {metric.code ? <code>{metric.value}</code> : metric.value}
                  </span>
                </div>
              ))}
            </div>
          </td>
          <td>
            <div class="car-list-actions">
              {row.primaryAction ? (
                <button
                  type="button"
                  class={row.primaryAction.className}
                  data-car-action={row.primaryAction.type}
                  data-car-id={row.carId}
                  onClick={() =>
                    void (row.primaryAction?.type === "activate"
                      ? activateCar(row.carId)
                      : completeCar(row.carId))
                  }
                >
                  {row.primaryAction.label}
                </button>
              ) : null}
              <button
                type="button"
                class="btn btn--danger-quiet car-delete-btn"
                data-car-action="delete"
                data-car-id={row.carId}
                onClick={() => void deleteCar(row.carId)}
              >
                {t("settings.car.delete")}
              </button>
            </div>
          </td>
        </tr>
      ))}
    </>
  );
}

export function Cars() {
  const banner = guidance(carSelection.value, highlighted.value, t);
  return (
    <>
      <div class="panel card">
        <div class="car-tab-header">
          <strong>{t("settings.car.manage")}</strong>
          <button
            id="addCarBtn"
            type="button"
            class="btn btn--success"
            onClick={() => void openWizard()}
          >
            {t("settings.car.add_new")}
          </button>
        </div>
        <div class="subtle">{t("settings.car.hint")}</div>
        <div id="carSelectionGuidance" hidden={banner === null}>
          {banner ? <InlineStatePanel state={banner} /> : null}
        </div>
        <div class="settings-table-wrap">
          <table class="car-list-table settings-entity-table settings-entity-table--cars">
            <thead>
              <tr>
                <th>{t("settings.car.col_name")}</th>
                <th>{t("settings.car.col_setup")}</th>
                <th>{t("settings.car.col_actions")}</th>
              </tr>
            </thead>
            <tbody id="carListBody">
              <CarTableBody />
            </tbody>
          </table>
        </div>
      </div>
      <CarWizard />
    </>
  );
}
