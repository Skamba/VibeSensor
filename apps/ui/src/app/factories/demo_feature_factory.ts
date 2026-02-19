import type { UiAppContext } from "../context/ui_app_context";
import { DemoFeatureController } from "../features/demo_feature";

export class DemoFeatureFactory {
  create(context: UiAppContext): DemoFeatureController {
    return new DemoFeatureController(context);
  }
}
