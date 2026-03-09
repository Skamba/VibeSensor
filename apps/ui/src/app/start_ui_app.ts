import "uplot/dist/uPlot.min.css";
import "../styles/app.css";
import { UiAppRuntime } from "./ui_app_runtime";

export function startUiApp(): void {
  new UiAppRuntime().start();
}
