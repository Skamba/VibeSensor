import { render } from "preact";

import { useUiText } from "../ui_i18n";
import {
  computed,
  signal,
  type ReadonlySignal,
} from "../ui_signals";

export interface RealtimeLiveOverviewActiveCarModel {
  text: string;
  warning: boolean;
}

export interface RealtimeLiveOverviewHealthModel {
  hidden: boolean;
  text: string;
  variant: "muted" | "ok" | "warn" | "bad";
}

export interface RealtimeLiveOverviewSensorCardModel {
  id: string;
  label: string;
  connected: boolean;
  statusText: string;
  strongest: boolean;
}

export interface RealtimeLiveOverviewRenderModel {
  connectedSensorsText: string;
  activeCar: RealtimeLiveOverviewActiveCarModel;
  recordingStateText: string;
  dataFreshnessText: string;
  strongestSignalText: string;
  runHealth: RealtimeLiveOverviewHealthModel;
  sensorCards: RealtimeLiveOverviewSensorCardModel[];
}

interface RealtimeLiveOverviewBridgeState {
  speedText: string;
}

export interface RealtimeLiveOverviewBridge {
  bindModel(model: ReadonlySignal<RealtimeLiveOverviewRenderModel>): void;
  setSpeedText(text: string): void;
}

const DEFAULT_OVERVIEW_MODEL: RealtimeLiveOverviewRenderModel = {
  connectedSensorsText: "--",
  activeCar: {
    text: "--",
    warning: false,
  },
  recordingStateText: "--",
  dataFreshnessText: "--",
  strongestSignalText: "--",
  runHealth: {
    hidden: false,
    text: "No live signal",
    variant: "muted",
  },
  sensorCards: [],
};

const DEFAULT_OVERVIEW_STATE: RealtimeLiveOverviewBridgeState = {
  speedText: "--",
};

function RealtimeLiveOverview(props: {
  model: ReadonlySignal<RealtimeLiveOverviewRenderModel>;
  speedText: ReadonlySignal<string>;
}) {
  const titleText = useUiText("dashboard.live_overview", "Live overview");
  const hintText = useUiText(
    "dashboard.live_overview_hint",
    "Check readiness, current run state, and the strongest sensor level before reading the chart.",
  );
  const connectedSensorsLabel = useUiText("dashboard.connected_sensors", "Sensors online");
  const activeCarLabel = useUiText("dashboard.active_car", "Active car");
  const recordingStateLabel = useUiText("dashboard.recording_state", "Run state");
  const dataFreshnessLabel = useUiText("dashboard.data_freshness", "Feed freshness");
  const strongestSignalLabel = useUiText("dashboard.strongest_signal", "Strongest signal");
  const currentSpeedLabel = useUiText("dashboard.current_speed", "Current speed");
  const sensorCoverageLabel = useUiText("dashboard.sensor_coverage", "Sensor coverage");
  const noSensorsText = useUiText("settings.sensors.no_sensors", "No sensors yet.");
  const model = props.model.value;
  const activeCarVariant = model.activeCar.warning ? "warn" : undefined;
  const activeCarHasIcon = model.activeCar.warning ? "true" : undefined;

  return (
    <>
      <div class="card__header card__header--stack">
        <div>
          <div class="card__title">
            {titleText}
          </div>
          <div class="card__subtle">
            {hintText}
          </div>
        </div>
        <div
          id="liveRunHealth"
          class="pill"
          data-variant={model.runHealth.variant}
          hidden={model.runHealth.hidden}
          aria-live="polite"
        >
          {model.runHealth.text}
        </div>
      </div>
      <div class="stat-grid live-overview__stats">
        <div id="liveConnectedSensors" class="stat">
          <div class="stat__label">
            {connectedSensorsLabel}
          </div>
          <div class="stat__value" data-value>
            {model.connectedSensorsText}
          </div>
        </div>
        <div
          id="liveActiveCar"
          class="stat"
          data-variant={activeCarVariant}
        >
          <div class="stat__label">
            {activeCarLabel}
          </div>
          <div
            class="stat__value"
            data-value
            data-variant={activeCarVariant}
            data-has-icon={activeCarHasIcon}
          >
            {model.activeCar.warning
              ? (
                <>
                  <span class="stat__value-icon" data-variant="warn" aria-hidden="true">
                    !
                  </span>
                  <span>{model.activeCar.text}</span>
                </>
              )
              : model.activeCar.text}
          </div>
        </div>
        <div id="liveRecordingState" class="stat">
          <div class="stat__label">
            {recordingStateLabel}
          </div>
          <div class="stat__value" data-value>
            {model.recordingStateText}
          </div>
        </div>
        <div id="liveDataFreshness" class="stat">
          <div class="stat__label">
            {dataFreshnessLabel}
          </div>
          <div class="stat__value" data-value>
            {model.dataFreshnessText}
          </div>
        </div>
        <div id="liveStrongestSignal" class="stat">
          <div class="stat__label">
            {strongestSignalLabel}
          </div>
          <div class="stat__value" data-value>
            {model.strongestSignalText}
          </div>
        </div>
        <div class="stat">
          <div class="stat__label">
            {currentSpeedLabel}
          </div>
          <div id="speed" class="stat__value speed" aria-live="polite">
            {props.speedText}
          </div>
        </div>
      </div>
      <div class="live-sensor-roster__header">
        <div class="mini-label">
          {sensorCoverageLabel}
        </div>
      </div>
      <div id="liveSensorRoster" class="live-sensor-roster">
        {model.sensorCards.length
          ? model.sensorCards.map((card) => {
            const statusClass = card.connected ? "online" : "offline";
            return (
              <article
                key={card.id}
                class={card.strongest ? "live-sensor-card live-sensor-card--strongest" : "live-sensor-card"}
              >
                <div class="live-sensor-card__header">
                  <strong>{card.label}</strong>
                  <span
                    class={`live-sensor-card__status-dot live-sensor-card__status-dot--${statusClass}`}
                    role="img"
                    aria-label={card.statusText}
                    title={card.statusText}
                  />
                </div>
              </article>
            );
          })
          : (
            <div class="subtle">
              {noSensorsText}
            </div>
          )}
      </div>
    </>
  );
}

export function mountRealtimeLiveOverview(host: HTMLElement): RealtimeLiveOverviewBridge {
  const modelSource = signal<ReadonlySignal<RealtimeLiveOverviewRenderModel> | null>(null);
  const model = computed<RealtimeLiveOverviewRenderModel>(() => modelSource.value?.value ?? DEFAULT_OVERVIEW_MODEL);
  const speedText = signal(DEFAULT_OVERVIEW_STATE.speedText);
  render(<RealtimeLiveOverview model={model} speedText={speedText} />, host);

  return {
    bindModel(model: ReadonlySignal<RealtimeLiveOverviewRenderModel>): void {
      modelSource.value = model;
    },
    setSpeedText(text: string): void {
      speedText.value = text;
    },
  };
}
