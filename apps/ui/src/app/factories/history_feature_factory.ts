import type { UiAppContext } from "../context/ui_app_context";
import { HistoryFeatureController } from "../features/history_feature";

export class HistoryFeatureFactory {
  create(context: UiAppContext): HistoryFeatureController {
    return new HistoryFeatureController(context);
  }
}
