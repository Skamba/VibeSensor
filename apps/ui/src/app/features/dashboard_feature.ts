import type { UiAppContext } from "../context/ui_app_context";
import type { UiAppFeatureController } from "../types/ui_app_feature";

export class DashboardFeatureController implements UiAppFeatureController {
  constructor(private readonly _context: UiAppContext) {}

  start(): void {}
}
