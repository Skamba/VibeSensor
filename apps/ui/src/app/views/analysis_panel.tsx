import { h } from "preact";

import { createUiPreactMount } from "../runtime/ui_preact_mount";

export interface SettingsAnalysisFieldGuidanceSlots {
  wheelBandwidth: HTMLElement | null;
  driveshaftBandwidth: HTMLElement | null;
  engineBandwidth: HTMLElement | null;
  speedUncertainty: HTMLElement | null;
  tireDiameterUncertainty: HTMLElement | null;
  finalDriveUncertainty: HTMLElement | null;
  gearUncertainty: HTMLElement | null;
  minAbsBandHz: HTMLElement | null;
  maxBandHalfWidth: HTMLElement | null;
}

export interface SettingsAnalysisPanelDom {
  wheelBandwidthInput: HTMLInputElement | null;
  driveshaftBandwidthInput: HTMLInputElement | null;
  engineBandwidthInput: HTMLInputElement | null;
  speedUncertaintyInput: HTMLInputElement | null;
  tireDiameterUncertaintyInput: HTMLInputElement | null;
  finalDriveUncertaintyInput: HTMLInputElement | null;
  gearUncertaintyInput: HTMLInputElement | null;
  minAbsBandHzInput: HTMLInputElement | null;
  maxBandHalfWidthInput: HTMLInputElement | null;
  saveAnalysisBtn: HTMLButtonElement | null;
  resetAnalysisBtn: HTMLButtonElement | null;
  analysisGuidanceHelp: HTMLDetailsElement | null;
  analysisFieldGuidance: SettingsAnalysisFieldGuidanceSlots;
  analysisSaveFeedback: HTMLElement | null;
  analysisNoCarMessage: HTMLElement | null;
}

export interface AnalysisPanelView {
  readonly dom: SettingsAnalysisPanelDom;
}

function AnalysisPanel() {
  return (
    <div class="panel card settings-layout">
      <div class="subtle" data-i18n="settings.analysis.hint">
        These settings apply globally to all cars and control how vibration
        frequency bands are calculated.
      </div>
      <details
        id="analysisGuidanceHelp"
        class="settings-help-disclosure settings-help-disclosure--banner"
      >
        <summary class="settings-help-disclosure__summary">
          <span class="settings-help-disclosure__heading">
            <strong
              class="settings-help-disclosure__title"
              data-i18n="settings.analysis.guidance_title"
            >
              Safe starting point
            </strong>
            <span
              class="settings-help-disclosure__caption"
              data-i18n="settings.analysis.guidance_summary"
            >
              Keep the defaults unless the data is unusually noisy or the
              vehicle specs are approximate.
            </span>
          </span>
        </summary>
        <div class="settings-help-disclosure__body">
          <div
            class="subtle"
            data-i18n="settings.analysis.guidance_intro"
          >
            Most users should keep the defaults. Use wider bands or higher
            uncertainty only when your data is unusually noisy or your vehicle
            specs are approximate.
          </div>
          <div
            class="subtle"
            data-i18n="settings.analysis.guidance_guardrail"
          >
            Values outside the guided range will ask for confirmation before
            they are saved.
          </div>
        </div>
      </details>
      <div
        id="analysisNoCarMessage"
        class="empty-state empty-state--inline"
        hidden
        data-i18n="settings.analysis.no_car_selected"
      >
        No car selected. Select or create a car in Settings → Car to save
        analysis settings.
      </div>
      <div class="settings-groups">
        <section class="settings-group">
          <h3 data-i18n="settings.group.order_band_widths">Order Band Widths</h3>
          <details
            id="analysisOrderBandHelp"
            class="settings-help-disclosure settings-help-disclosure--inline"
          >
            <summary class="settings-help-disclosure__summary">
              <span
                class="settings-help-disclosure__title"
                data-i18n="settings.analysis.more_guidance"
              >
                Why this matters
              </span>
            </summary>
            <div class="settings-help-disclosure__body">
              <div
                class="subtle"
                data-i18n="settings.analysis.group.order_band_widths_help"
              >
                These values control how far the app searches around each
                expected order. Wider bands tolerate more speed drift but can
                blend nearby faults together.
              </div>
            </div>
          </details>
          <div class="settings-subgrid">
            <div class="field">
              <label
                htmlFor="wheelBandwidthInput"
                data-i18n="settings.wheel_bandwidth"
              >
                Wheel Bandwidth (%)
              </label>
              <input id="wheelBandwidthInput" type="number" step="0.1" />
              <div
                id="wheelBandwidthGuidance"
                class="subtle settings-field-guidance"
              ></div>
            </div>
            <div class="field">
              <label
                htmlFor="driveshaftBandwidthInput"
                data-i18n="settings.driveshaft_bandwidth"
              >
                Driveshaft Bandwidth (%)
              </label>
              <input id="driveshaftBandwidthInput" type="number" step="0.1" />
              <div
                id="driveshaftBandwidthGuidance"
                class="subtle settings-field-guidance"
              ></div>
            </div>
            <div class="field">
              <label
                htmlFor="engineBandwidthInput"
                data-i18n="settings.engine_bandwidth"
              >
                Engine Bandwidth (%)
              </label>
              <input id="engineBandwidthInput" type="number" step="0.1" />
              <div
                id="engineBandwidthGuidance"
                class="subtle settings-field-guidance"
              ></div>
            </div>
            <div class="field">
              <label
                htmlFor="minAbsBandHzInput"
                data-i18n="settings.min_half_width"
              >
                Min Half-width (Hz)
              </label>
              <input id="minAbsBandHzInput" type="number" step="0.1" />
              <div
                id="minAbsBandHzGuidance"
                class="subtle settings-field-guidance"
              ></div>
            </div>
            <div class="field">
              <label
                htmlFor="maxBandHalfWidthInput"
                data-i18n="settings.max_half_width"
              >
                Max Half-width (%)
              </label>
              <input id="maxBandHalfWidthInput" type="number" step="0.1" />
              <div
                id="maxBandHalfWidthGuidance"
                class="subtle settings-field-guidance"
              ></div>
            </div>
          </div>
        </section>

        <section class="settings-group">
          <h3 data-i18n="settings.group.uncertainty_model">Uncertainty Model</h3>
          <details
            id="analysisUncertaintyHelp"
            class="settings-help-disclosure settings-help-disclosure--inline"
          >
            <summary class="settings-help-disclosure__summary">
              <span
                class="settings-help-disclosure__title"
                data-i18n="settings.analysis.more_guidance"
              >
                Why this matters
              </span>
            </summary>
            <div class="settings-help-disclosure__body">
              <div class="subtle">
                <span data-i18n="settings.uncertainty_defaults">
                  Defaults use tire wear from 10/32 in to 2/32 in plus safety
                  margin.
                </span>
              </div>
              <div
                class="subtle"
                data-i18n="settings.analysis.group.uncertainty_model_help"
              >
                Use these only when vehicle data is approximate, modified, or
                worn. Higher uncertainty makes matching more tolerant, but it
                can lower specificity and confidence.
              </div>
            </div>
          </details>
          <div class="settings-subgrid settings-subgrid--aligned-labels">
            <div class="field">
              <label
                htmlFor="speedUncertaintyInput"
                data-i18n="settings.speed_uncertainty"
              >
                Speed Uncertainty (%)
              </label>
              <input id="speedUncertaintyInput" type="number" step="0.1" />
              <div
                id="speedUncertaintyGuidance"
                class="subtle settings-field-guidance"
              ></div>
            </div>
            <div class="field">
              <label
                htmlFor="tireDiameterUncertaintyInput"
                data-i18n="settings.tire_diameter_uncertainty"
              >
                Tire Diameter Uncertainty (%)
              </label>
              <input
                id="tireDiameterUncertaintyInput"
                type="number"
                step="0.1"
              />
              <div
                id="tireDiameterUncertaintyGuidance"
                class="subtle settings-field-guidance"
              ></div>
            </div>
            <div class="field">
              <label
                htmlFor="finalDriveUncertaintyInput"
                data-i18n="settings.final_drive_uncertainty"
              >
                Final Drive Uncertainty (%)
              </label>
              <input
                id="finalDriveUncertaintyInput"
                type="number"
                step="0.1"
              />
              <div
                id="finalDriveUncertaintyGuidance"
                class="subtle settings-field-guidance"
              ></div>
            </div>
            <div class="field">
              <label
                htmlFor="gearUncertaintyInput"
                data-i18n="settings.gear_slip_uncertainty"
              >
                Gear/Slip Uncertainty (%)
              </label>
              <input id="gearUncertaintyInput" type="number" step="0.1" />
              <div
                id="gearUncertaintyGuidance"
                class="subtle settings-field-guidance"
              ></div>
            </div>
          </div>
        </section>
      </div>
      <div id="analysisSaveFeedback" class="settings-feedback-slot" hidden></div>
      <div class="settings-actions">
        <button
          id="resetAnalysisBtn"
          class="btn"
          data-i18n="settings.analysis.reset"
        >
          Reset to defaults
        </button>
        <button
          id="saveAnalysisBtn"
          class="btn btn--primary"
          data-i18n="settings.analysis.save"
        >
          Save Analysis Settings
        </button>
      </div>
    </div>
  );
}

function createAnalysisPanelDom(host: HTMLElement): SettingsAnalysisPanelDom {
  const queryById = <T extends HTMLElement>(id: string): T | null =>
    host.querySelector<T>(`#${id}`);

  return {
    wheelBandwidthInput: queryById<HTMLInputElement>("wheelBandwidthInput"),
    driveshaftBandwidthInput: queryById<HTMLInputElement>(
      "driveshaftBandwidthInput",
    ),
    engineBandwidthInput: queryById<HTMLInputElement>("engineBandwidthInput"),
    speedUncertaintyInput: queryById<HTMLInputElement>("speedUncertaintyInput"),
    tireDiameterUncertaintyInput: queryById<HTMLInputElement>(
      "tireDiameterUncertaintyInput",
    ),
    finalDriveUncertaintyInput: queryById<HTMLInputElement>(
      "finalDriveUncertaintyInput",
    ),
    gearUncertaintyInput: queryById<HTMLInputElement>("gearUncertaintyInput"),
    minAbsBandHzInput: queryById<HTMLInputElement>("minAbsBandHzInput"),
    maxBandHalfWidthInput: queryById<HTMLInputElement>("maxBandHalfWidthInput"),
    saveAnalysisBtn: queryById<HTMLButtonElement>("saveAnalysisBtn"),
    resetAnalysisBtn: queryById<HTMLButtonElement>("resetAnalysisBtn"),
    analysisGuidanceHelp: queryById<HTMLDetailsElement>("analysisGuidanceHelp"),
    analysisFieldGuidance: {
      wheelBandwidth: queryById<HTMLElement>("wheelBandwidthGuidance"),
      driveshaftBandwidth: queryById<HTMLElement>("driveshaftBandwidthGuidance"),
      engineBandwidth: queryById<HTMLElement>("engineBandwidthGuidance"),
      speedUncertainty: queryById<HTMLElement>("speedUncertaintyGuidance"),
      tireDiameterUncertainty: queryById<HTMLElement>(
        "tireDiameterUncertaintyGuidance",
      ),
      finalDriveUncertainty: queryById<HTMLElement>(
        "finalDriveUncertaintyGuidance",
      ),
      gearUncertainty: queryById<HTMLElement>("gearUncertaintyGuidance"),
      minAbsBandHz: queryById<HTMLElement>("minAbsBandHzGuidance"),
      maxBandHalfWidth: queryById<HTMLElement>("maxBandHalfWidthGuidance"),
    },
    analysisSaveFeedback: queryById<HTMLElement>("analysisSaveFeedback"),
    analysisNoCarMessage: queryById<HTMLElement>("analysisNoCarMessage"),
  };
}

export function mountAnalysisPanel(host: HTMLElement): AnalysisPanelView {
  createUiPreactMount(host).render(<AnalysisPanel />);
  return {
    dom: createAnalysisPanelDom(host),
  };
}
