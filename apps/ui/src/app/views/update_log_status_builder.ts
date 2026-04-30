import type { UpdateStatusPayload } from "../../api/types";
import type {
  UpdateLogSectionModel,
  UpdateStatusViewDeps,
} from "./update_status_models";

export function buildUpdateLogSectionModel(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): UpdateLogSectionModel {
  const isRunning = status.state === "running";
  if (status.log_tail.length === 0) {
    return {
      titleText: deps.t("settings.update.log"),
      subtitleText: deps.t(
        isRunning
          ? "settings.update.log_intro_running"
          : "settings.update.log_intro",
      ),
      noteText: null,
      lines: [],
      emptyState: {
        titleText: isRunning
          ? deps.t("settings.update.log_running_title")
          : status.state === "failed"
            ? deps.t("settings.update.log_failed_title")
            : deps.t("settings.update.log_empty_title"),
        bodyText: isRunning
          ? deps.t("settings.update.log_running_body")
          : status.state === "failed"
            ? deps.t("settings.update.log_failed_body")
            : deps.t("settings.update.log_empty_body"),
      },
    };
  }
  return {
    titleText: deps.t("settings.update.log"),
    subtitleText: deps.t(
      isRunning
        ? "settings.update.log_intro_running"
        : "settings.update.log_intro",
    ),
    noteText: isRunning ? deps.t("settings.update.log_running_note") : null,
    lines: [...status.log_tail],
    emptyState: null,
  };
}
