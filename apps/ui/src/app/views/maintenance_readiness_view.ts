import { h } from "preact";

import type { VisualVariant } from "../view_style_types";

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
  stateVariant: VisualVariant;
  items: readonly MaintenanceReadinessItem[];
}

function MaintenanceReadinessItemRow(props: {
  item: MaintenanceReadinessItem;
}) {
  const { item } = props;
  const marker = item.state === "ready" ? "\u2713" : "!";
  return h(
    "li",
    {
      class: "maintenance-readiness__item",
      "data-readiness-state": item.state,
    },
    h(
      "span",
      {
        "aria-hidden": "true",
        class: "maintenance-readiness__marker",
      },
      marker,
    ),
    h(
      "div",
      { class: "maintenance-readiness__body" },
      h("div", { class: "maintenance-readiness__label" }, item.label),
      h("div", { class: "maintenance-readiness__detail" }, item.detail),
    ),
  );
}

export function MaintenanceReadinessPanel(props: {
  model: MaintenanceReadinessPanelModel;
}) {
  const { model } = props;
  return h(
    "section",
    { class: "maintenance-readiness" },
    h(
      "div",
      { class: "maintenance-readiness__header" },
      h(
        "div",
        { class: "maintenance-readiness__heading" },
        h("div", { class: "maintenance-readiness__title" }, model.title),
        h("div", { class: "maintenance-readiness__summary" }, model.summary),
      ),
      model.stateLabel
        ? h(
            "span",
            { class: "pill", "data-variant": model.stateVariant },
            model.stateLabel,
          )
        : null,
    ),
    h(
      "ul",
      { class: "maintenance-readiness__list" },
      model.items.map((item, index) =>
        h(MaintenanceReadinessItemRow, {
          item,
          key: `${item.label}:${index}`,
        }),
      ),
    ),
  );
}
