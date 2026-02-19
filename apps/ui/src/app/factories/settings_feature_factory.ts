import type { UiAppContext } from "../context/ui_app_context";
import { SettingsFeatureController } from "../features/settings_feature";

export class SettingsFeatureFactory {
  create(context: UiAppContext): SettingsFeatureController {
    return new SettingsFeatureController(context);
  }
}
