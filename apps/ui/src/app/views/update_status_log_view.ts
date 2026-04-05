import { createElementNode } from "./dom_render";
import {
  createInlineEmptyStateElement,
  createMaintenanceCardElement,
  createMaintenanceNoteElement,
} from "./update_status_section_helpers";
import type { UpdateLogSectionModel } from "./update_status_view_models";

export function createUpdateLogCard(
  model: UpdateLogSectionModel,
): HTMLElement {
  const logBody = model.lines.map((line) => `${line}\n`).join("");
  return createMaintenanceCardElement({
    titleText: model.titleText,
    subtitleText: model.subtitleText,
    bodyChildren: model.emptyState
      ? [createInlineEmptyStateElement(model.emptyState)]
      : [
          model.noteText ? createMaintenanceNoteElement(model.noteText) : null,
          createElementNode("pre", {
            className: "log-pre",
            text: logBody,
          }),
        ],
  });
}
