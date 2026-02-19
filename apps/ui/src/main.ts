import { UiAppFactory } from "./app/factories/ui_app_factory";
import { startLegacyUiApp } from "./legacy_main_runtime";

new UiAppFactory({ startLegacyUiApp }).create().start();
