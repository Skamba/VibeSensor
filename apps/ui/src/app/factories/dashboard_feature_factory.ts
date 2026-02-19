import type { UiAppContext } from "../context/ui_app_context";
import { DashboardFeatureController } from "../features/dashboard_feature";

export class DashboardFeatureFactory {
  create(context: UiAppContext): DashboardFeatureController {
    return new DashboardFeatureController(context);
  }
}
