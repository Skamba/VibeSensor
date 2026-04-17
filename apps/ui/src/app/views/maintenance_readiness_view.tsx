export type MaintenanceReadinessItemState = "attention" | "blocked" | "ready";
type VisualVariant = "bad" | "muted" | "ok" | "warn";

export interface MaintenanceReadinessItem {
  label: string;
  detail: string;
  state: MaintenanceReadinessItemState;
}

export interface MaintenanceReadinessPanelModel {
  title: string;
  summary: string;
  stateLabel: string;
  stateVariant: VisualVariant;
  items: readonly MaintenanceReadinessItem[];
}

function MaintenanceReadinessItemRow(props: {
  item: MaintenanceReadinessItem;
}) {
  const { item } = props;
  const marker = item.state === "ready" ? "\u2713" : "!";
  return (
    <li class="maintenance-readiness__item" data-readiness-state={item.state}>
      <span aria-hidden="true" class="maintenance-readiness__marker">
        {marker}
      </span>
      <div class="maintenance-readiness__body">
        <div class="maintenance-readiness__label">{item.label}</div>
        <div class="maintenance-readiness__detail">{item.detail}</div>
      </div>
    </li>
  );
}

export function MaintenanceReadinessPanel(props: {
  model: MaintenanceReadinessPanelModel;
}) {
  const { model } = props;
  return (
    <section class="maintenance-readiness">
      <div class="maintenance-readiness__header">
        <div class="maintenance-readiness__heading">
          <div class="maintenance-readiness__title">{model.title}</div>
          <div class="maintenance-readiness__summary">{model.summary}</div>
        </div>
        {model.stateLabel
          ? (
            <span class="pill" data-variant={model.stateVariant}>
              {model.stateLabel}
            </span>
          )
          : null}
      </div>
      <ul class="maintenance-readiness__list">
        {model.items.map((item, index) => (
          <MaintenanceReadinessItemRow
            key={`${item.label}:${index}`}
            item={item}
          />
        ))}
      </ul>
    </section>
  );
}
