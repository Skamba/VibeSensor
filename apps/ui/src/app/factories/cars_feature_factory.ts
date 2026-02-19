import type { UiAppContext } from "../context/ui_app_context";
import { CarsFeatureController } from "../features/cars_feature";

export class CarsFeatureFactory {
  create(context: UiAppContext): CarsFeatureController {
    return new CarsFeatureController(context);
  }
}
