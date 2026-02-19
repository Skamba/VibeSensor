import type { UiAppContext } from "../context/ui_app_context";
import type { UiAppFeatureController } from "../types/ui_app_feature";

export class RealtimeFeatureController implements UiAppFeatureController {
  constructor(private readonly context: UiAppContext) {}

  start(): void {
    if (this.context.state.started) return;
    this.context.state.started = true;
    this.context.deps.startLegacyUiApp();
  }
}
