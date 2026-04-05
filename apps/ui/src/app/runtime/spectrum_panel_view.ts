import type { UiSpectrumDom } from "../dom/spectrum_dom";

export type SpectrumLegendState = "all-visible" | "visible" | "isolated" | "inactive";

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

type SpectrumLegendButton = {
  button: HTMLButtonElement;
  label: HTMLSpanElement;
  meta: HTMLSpanElement | null;
  swatch: HTMLSpanElement | null;
};

export interface SpectrumPanelView {
  bindBandToggle(onToggle: () => void): void;
  renderBandToggle(model: {
    hasBands: boolean;
    bandsVisible: boolean;
    text: string;
  }): void;
  renderSensorLegend(
    model: SpectrumSensorLegendModel | null,
    handlers?: {
      onReset: () => void;
      onSelect: (entryId: string) => void;
    },
  ): void;
  renderBandLegend(model: SpectrumBandLegendModel): void;
  renderInspectorText(text: string): void;
}

export interface SpectrumPanelViewDeps {
  dom: Pick<
    UiSpectrumDom,
    "bandLegend" | "legend" | "spectrumBandToggle" | "spectrumInspector"
  >;
}

export function createSpectrumPanelView(
  deps: SpectrumPanelViewDeps,
): SpectrumPanelView {
  let legendResetButton: SpectrumLegendButton | null = null;
  const legendSeriesButtons = new Map<string, SpectrumLegendButton>();

  function setOptionalStateAttribute(
    element: HTMLElement,
    name: string,
    value: string | null,
  ): void {
    if (!value) {
      element.removeAttribute(name);
      return;
    }
    element.setAttribute(name, value);
  }

  function bindBandToggle(onToggle: () => void): void {
    deps.dom.spectrumBandToggle?.addEventListener("click", onToggle);
  }

  function renderBandToggle(model: {
    hasBands: boolean;
    bandsVisible: boolean;
    text: string;
  }): void {
    const button = deps.dom.spectrumBandToggle;
    if (!button) {
      return;
    }
    button.setAttribute("aria-controls", "bandLegend");
    button.hidden = !model.hasBands;
    button.disabled = !model.hasBands;
    button.setAttribute("aria-pressed", model.hasBands && model.bandsVisible ? "true" : "false");
    button.setAttribute("aria-expanded", model.hasBands && model.bandsVisible ? "true" : "false");
    button.textContent = model.text;
  }

  function renderSensorLegend(
    model: SpectrumSensorLegendModel | null,
    handlers?: {
      onReset: () => void;
      onSelect: (entryId: string) => void;
    },
  ): void {
    const legend = deps.dom.legend;
    if (!legend) {
      return;
    }
    if (!model || model.items.length === 0 || !handlers) {
      legendResetButton?.button.remove();
      for (const parts of legendSeriesButtons.values()) {
        parts.button.remove();
      }
      legendResetButton = null;
      legendSeriesButtons.clear();
      return;
    }

    const allButton = ensureLegendResetButton(handlers.onReset);
    allButton.button.className = "legend-item legend-item--interactive legend-item--reset";
    allButton.button.setAttribute("aria-pressed", model.reset.ariaPressed ? "true" : "false");
    allButton.button.title = model.reset.titleText;
    allButton.button.setAttribute("aria-label", model.reset.ariaLabel);
    setOptionalStateAttribute(allButton.button, "data-legend-state", model.reset.active ? "active" : null);
    allButton.label.textContent = model.reset.labelText;
    placeLegendButton(legend, allButton.button, 0);

    const activeIds = new Set<string>();
    let nextIndex = 1;
    for (const item of model.items) {
      activeIds.add(item.id);
      const parts = ensureLegendSeriesButton(item.id, handlers.onSelect);
      parts.button.className = "legend-item legend-item--interactive";
      parts.button.setAttribute("aria-pressed", item.ariaPressed ? "true" : "false");
      parts.button.title = item.titleText;
      parts.button.setAttribute("aria-label", item.ariaLabel);
      setOptionalStateAttribute(
        parts.button,
        "data-legend-state",
        item.active ? "active" : item.muted ? "muted" : null,
      );
      parts.label.textContent = item.labelText;
      parts.swatch?.style.setProperty("--swatch-color", item.color);
      if (parts.meta) {
        parts.meta.textContent = item.detailText ?? "";
      }
      placeLegendButton(legend, parts.button, nextIndex);
      nextIndex += 1;
    }

    for (const [entryId, parts] of legendSeriesButtons) {
      if (activeIds.has(entryId)) {
        continue;
      }
      parts.button.remove();
      legendSeriesButtons.delete(entryId);
    }
  }

  function renderBandLegend(model: SpectrumBandLegendModel): void {
    const legend = deps.dom.bandLegend;
    if (!legend) {
      return;
    }
    legend.innerHTML = "";
    legend.hidden = !model.visible;
    if (!model.visible) {
      return;
    }
    if (!model.items.length) {
      const row = document.createElement("div");
      row.className = "legend-item legend-item--band";
      row.setAttribute("data-band-state", "empty");
      row.textContent = model.emptyText;
      legend.appendChild(row);
      return;
    }
    for (const item of model.items) {
      const row = document.createElement("div");
      row.className = "legend-item legend-item--band";
      row.setAttribute("data-band-state", "active");
      row.style.setProperty("--band-color", item.color);
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.setProperty("--swatch-color", item.color);
      const label = document.createElement("span");
      label.textContent = item.labelText;
      row.append(swatch, label);
      legend.appendChild(row);
    }
  }

  function renderInspectorText(text: string): void {
    if (!deps.dom.spectrumInspector) {
      return;
    }
    deps.dom.spectrumInspector.textContent = text;
  }

  function ensureLegendResetButton(onReset: () => void): SpectrumLegendButton {
    if (legendResetButton) {
      return legendResetButton;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.addEventListener("click", onReset);
    const label = document.createElement("span");
    label.className = "legend-item__label";
    button.appendChild(label);
    legendResetButton = {
      button,
      label,
      meta: null,
      swatch: null,
    };
    return legendResetButton;
  }

  function ensureLegendSeriesButton(
    entryId: string,
    onSelect: (entryId: string) => void,
  ): SpectrumLegendButton {
    const existing = legendSeriesButtons.get(entryId);
    if (existing) {
      return existing;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.addEventListener("click", () => onSelect(entryId));

    const swatch = document.createElement("span");
    swatch.className = "swatch";

    const textGroup = document.createElement("span");
    textGroup.className = "legend-item__text-group";

    const label = document.createElement("span");
    label.className = "legend-item__label";

    const meta = document.createElement("span");
    meta.className = "legend-item__meta";

    textGroup.append(label, meta);
    button.append(swatch, textGroup);

    const created = {
      button,
      label,
      meta,
      swatch,
    };
    legendSeriesButtons.set(entryId, created);
    return created;
  }

  function placeLegendButton(
    legend: HTMLElement,
    button: HTMLButtonElement,
    index: number,
  ): void {
    const currentChild = legend.children[index];
    if (currentChild === button) {
      return;
    }
    legend.insertBefore(button, currentChild ?? null);
  }

  return {
    bindBandToggle,
    renderBandToggle,
    renderSensorLegend,
    renderBandLegend,
    renderInspectorText,
  };
}
