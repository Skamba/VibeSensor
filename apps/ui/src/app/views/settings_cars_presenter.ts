import type { CarSelectionState } from "../car_selection_state";
import type { UiSettingsDom } from "../dom/settings_dom";
import type { CarRecord } from "../../transport/http_models";
import {
  renderInlineStatePanel,
} from "./dom_helpers";
import { renderSettingsCarList } from "./settings_car_list_view";

export interface SettingsCarsHighlightedFeedback {
  carId: string;
  carName: string;
}

export interface SettingsCarsRenderState {
  activeCarId: string | null;
  carSelectionState: CarSelectionState;
  cars: readonly CarRecord[];
  highlightedCarFeedback: SettingsCarsHighlightedFeedback | null;
}

export interface SettingsCarsPresenterDeps {
  dom: Pick<
    UiSettingsDom,
    | "analysisNoCarMessage"
    | "carListBody"
    | "carSelectionGuidance"
    | "resetAnalysisBtn"
    | "saveAnalysisBtn"
  >;
  escapeHtml: (value: unknown) => string;
  fmt: (value: number, digits?: number) => string;
  t: (key: string, vars?: Record<string, unknown>) => string;
}

export interface SettingsCarsPresenter {
  render(state: SettingsCarsRenderState): void;
}

function renderCreationFeedback(
  feedback: SettingsCarsHighlightedFeedback,
  deps: Pick<SettingsCarsPresenterDeps, "escapeHtml" | "t">,
): string {
  return `
    <div class="empty-state empty-state--inline car-selection-feedback car-selection-feedback--success" role="status">
      <strong class="empty-state__title">${deps.escapeHtml(deps.t("settings.car.created_title"))}</strong>
      <span class="empty-state__body">${deps.escapeHtml(
        deps.t("settings.car.created_body", { name: feedback.carName }),
      )}</span>
      <span class="empty-state__detail">${deps.escapeHtml(deps.t("settings.car.created_detail"))}</span>
    </div>
  `;
}

export function createSettingsCarsPresenter(
  deps: SettingsCarsPresenterDeps,
): SettingsCarsPresenter {
  const { dom, escapeHtml, fmt, t } = deps;

  function renderGuidance(state: SettingsCarsRenderState): void {
    const guidance = dom.carSelectionGuidance;
    if (!guidance) {
      return;
    }
    if (
      state.carSelectionState.kind === "loading"
      || state.carSelectionState.kind === "no_cars"
    ) {
      guidance.hidden = true;
      guidance.replaceChildren();
      return;
    }
    if (state.carSelectionState.kind === "active" && state.highlightedCarFeedback) {
      guidance.hidden = false;
      guidance.innerHTML = renderCreationFeedback(state.highlightedCarFeedback, { escapeHtml, t });
      return;
    }
    if (state.carSelectionState.kind === "active") {
      guidance.hidden = true;
      guidance.replaceChildren();
      return;
    }
    guidance.hidden = false;
    guidance.innerHTML = renderInlineStatePanel({
      titleHtml: escapeHtml(t("settings.car.guidance.no_active_title")),
      bodyHtml: escapeHtml(t("settings.car.guidance.no_active")),
      detailHtml: escapeHtml(t("settings.car.guidance.no_active_detail")),
    });
  }

  function syncAnalysisControls(state: SettingsCarsRenderState): void {
    const hasActiveCar = state.carSelectionState.kind === "active";
    if (dom.saveAnalysisBtn) {
      dom.saveAnalysisBtn.disabled = !hasActiveCar;
    }
    if (dom.resetAnalysisBtn) {
      dom.resetAnalysisBtn.disabled = !hasActiveCar;
    }
    if (dom.analysisNoCarMessage) {
      dom.analysisNoCarMessage.hidden = hasActiveCar || state.carSelectionState.kind === "loading";
    }
  }

  function renderCarList(state: SettingsCarsRenderState): void {
    if (!dom.carListBody || state.carSelectionState.kind === "loading") {
      return;
    }
    renderSettingsCarList(dom.carListBody, {
      activeCarId: state.activeCarId,
      cars: [...state.cars],
      highlightedCarId: state.highlightedCarFeedback?.carId ?? null,
      escapeHtml,
      fmt,
      t,
    });
  }

  return {
    render(state): void {
      syncAnalysisControls(state);
      renderGuidance(state);
      renderCarList(state);
    },
  };
}
