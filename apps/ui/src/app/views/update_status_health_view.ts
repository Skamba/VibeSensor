import { createMaintenanceCardElement, createStatusGridElement } from "./update_status_section_helpers";
import type { UpdateHealthSectionModel } from "./update_status_view_models";

export function createUpdateHealthCard(
  model: UpdateHealthSectionModel,
): HTMLElement {
  return createMaintenanceCardElement({
    titleText: model.titleText,
    subtitleText: model.summaryText,
    badge: model.badge,
    bodyChildren: [createStatusGridElement(model.rows)],
  });
}
