import type { ReadonlySignal } from "../ui_signals";

export type SpectrumLegendState = "all-visible" | "visible" | "isolated" | "inactive";

export interface SpectrumPanelHeaderModel {
  titleText: string;
  hintText: string;
}

export interface SpectrumLegendResetModel {
  labelText: string;
  titleText: string;
  ariaLabel: string;
  ariaPressed: boolean;
  active: boolean;
}

export interface SpectrumLegendItemModel {
  id: string;
  labelText: string;
  color: string;
  detailText: string | null;
  titleText: string;
  ariaLabel: string;
  ariaPressed: boolean;
  active: boolean;
  muted: boolean;
}

export interface SpectrumSensorLegendModel {
  reset: SpectrumLegendResetModel;
  items: readonly SpectrumLegendItemModel[];
}

export interface SpectrumBandLegendItemModel {
  labelText: string;
  color: string;
}

export interface SpectrumBandLegendModel {
  visible: boolean;
  items: readonly SpectrumBandLegendItemModel[];
  emptyText: string;
}

export interface SpectrumPanelChartDom {
  specChartWrap: HTMLElement;
  specChart: HTMLElement;
}

export interface SpectrumPanelBandToggleModel {
  hasBands: boolean;
  bandsVisible: boolean;
  text: string;
}

export interface SpectrumLegendHandlers {
  onReset: () => void;
  onSelect: (entryId: string) => void;
}

export interface SpectrumPanelView {
  readonly chartDom: SpectrumPanelChartDom;
  bindBandToggle(onToggle: () => void): void;
  bindBandToggleModel(model: ReadonlySignal<SpectrumPanelBandToggleModel>): void;
  bindSensorLegendModel(
    model: ReadonlySignal<SpectrumSensorLegendModel | null>,
    handlers: ReadonlySignal<SpectrumLegendHandlers | null>,
  ): void;
  bindBandLegendModel(model: ReadonlySignal<SpectrumBandLegendModel>): void;
  renderHeader(model: SpectrumPanelHeaderModel): void;
  renderOverlay(message: string | null): void;
  renderInspectorText(text: string): void;
}
