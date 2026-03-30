export type MaintenanceReadinessItemState = "attention" | "blocked" | "ready";

export interface MaintenanceReadinessItem {
  label: string;
  detail: string;
  state: MaintenanceReadinessItemState;
}

export interface MaintenanceReadinessPanelModel {
  title: string;
  summary: string;
  stateLabel: string;
  stateVariant: "bad" | "muted" | "ok" | "warn";
  items: readonly MaintenanceReadinessItem[];
}

function renderItem(
  item: MaintenanceReadinessItem,
  escapeHtml: (value: unknown) => string,
): string {
  const marker = item.state === "ready" ? "✓" : "!";
  return `<li class="maintenance-readiness__item maintenance-readiness__item--${item.state}">
    <span class="maintenance-readiness__marker" aria-hidden="true">${marker}</span>
    <div class="maintenance-readiness__body">
      <div class="maintenance-readiness__label">${escapeHtml(item.label)}</div>
      <div class="maintenance-readiness__detail">${escapeHtml(item.detail)}</div>
    </div>
  </li>`;
}

export function renderMaintenanceReadinessPanel(
  model: MaintenanceReadinessPanelModel,
  escapeHtml: (value: unknown) => string,
): string {
  const items = model.items.map((item) => renderItem(item, escapeHtml)).join("");
  return `<section class="maintenance-readiness">
    <div class="maintenance-readiness__header">
      <div class="maintenance-readiness__heading">
        <div class="maintenance-readiness__title">${escapeHtml(model.title)}</div>
        <div class="maintenance-readiness__summary">${escapeHtml(model.summary)}</div>
      </div>
      <span class="pill pill--${model.stateVariant}">${escapeHtml(model.stateLabel)}</span>
    </div>
    <ul class="maintenance-readiness__list">${items}</ul>
  </section>`;
}
