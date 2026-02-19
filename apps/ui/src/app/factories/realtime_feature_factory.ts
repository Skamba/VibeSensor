import type { UiAppContext } from "../context/ui_app_context";
import { RealtimeFeatureController } from "../features/realtime_feature";

export class RealtimeFeatureFactory {
  create(context: UiAppContext): RealtimeFeatureController {
    return new RealtimeFeatureController(context);
  }
}
