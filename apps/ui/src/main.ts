import { UiAppFactory } from "./app/factories/ui_app_factory";
import { startLegacyUiApp } from "./legacy_stub";

new UiAppFactory({ startLegacyUiApp }).create().start();
