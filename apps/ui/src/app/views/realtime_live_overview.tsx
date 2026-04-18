import { render } from "preact";

import { getUiText } from "../ui_i18n";
import {
  useComputed,
  useSignalProperties,
  type Signal,
  type ReadonlySignal,
} from "../ui_signals";
import { type DeferredModelSignal } from "./view_model_binding";

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
  model: DeferredModelSignal<RealtimeLiveOverviewRenderModel>;
  speedText: Signal<string>;
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

const REALTIME_LIVE_OVERVIEW_MODEL_KEYS = [
  "activeCar",
  "connectedSensorsText",
  "dataFreshnessText",
  "recordingStateText",
  "runHealth",
  "sensorCards",
  "strongestSignalText",
] as const;

function RealtimeLiveOverviewRunHealthPill(props: {
  runHealth: ReadonlySignal<RealtimeLiveOverviewHealthModel>;
}) {
  const { hidden, text, variant } = useSignalProperties(
    props.runHealth,
    ["hidden", "text", "variant"] as const,
  );

  return (
    <div
      id="liveRunHealth"
      class="pill"
      data-variant={variant}
      hidden={hidden}
      aria-live="polite"
    >
      {text}
    </div>
  );
}

function RealtimeLiveOverviewActiveCarStat(props: {
  activeCar: ReadonlySignal<RealtimeLiveOverviewActiveCarModel>;
  labelText: string;
}) {
  const { text, warning } = useSignalProperties(props.activeCar, ["text", "warning"] as const);
  const variant = useComputed(() => warning.value ? "warn" : undefined);
  const hasIcon = useComputed(() => warning.value ? "true" : undefined);

  return (
    <div
      id="liveActiveCar"
      class="stat"
      data-variant={variant}
    >
        <div class="stat__label">
          {props.labelText}
        </div>
      <div
        class="stat__value"
        data-value
        data-variant={variant}
        data-has-icon={hasIcon}
      >
        {warning.value
          ? (
            <>
              <span class="stat__value-icon" data-variant="warn" aria-hidden="true">
                !
              </span>
              <span>{text}</span>
            </>
          )
          : text}
      </div>
    </div>
  );
}

function RealtimeLiveOverviewSensorRoster(props: {
  sensorCards: ReadonlySignal<RealtimeLiveOverviewSensorCardModel[]>;
  noSensorsText: string;
}) {
  const hasSensorCards = useComputed(() => props.sensorCards.value.length > 0);

  return (
    <div id="liveSensorRoster" class="live-sensor-roster">
      {hasSensorCards.value
        ? props.sensorCards.value.map((card) => {
          const statusClass = card.connected ? "online" : "offline";
          return (
            <article
              key={card.id}
              class="live-sensor-card"
              data-strongest={card.strongest ? "true" : undefined}
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
            {props.noSensorsText}
          </div>
        )}
    </div>
  );
}

function RealtimeLiveOverview(props: {
  model: ReadonlySignal<ReadonlySignal<RealtimeLiveOverviewRenderModel> | null>;
  speedText: ReadonlySignal<string>;
}) {
  const labels = useComputed(() => ({
    activeCarLabel: getUiText("dashboard.active_car", "Active car"),
    connectedSensorsLabel: getUiText("dashboard.connected_sensors", "Sensors online"),
    currentSpeedLabel: getUiText("dashboard.current_speed", "Current speed"),
    dataFreshnessLabel: getUiText("dashboard.data_freshness", "Feed freshness"),
    hintText: getUiText(
      "dashboard.live_overview_hint",
      "Check readiness, current run state, and the strongest sensor level before reading the chart.",
    ),
    noSensorsText: getUiText("settings.sensors.no_sensors", "No sensors yet."),
    recordingStateLabel: getUiText("dashboard.recording_state", "Run state"),
    sensorCoverageLabel: getUiText("dashboard.sensor_coverage", "Sensor coverage"),
    strongestSignalLabel: getUiText("dashboard.strongest_signal", "Strongest signal"),
    titleText: getUiText("dashboard.live_overview", "Live overview"),
  }));
  const model = useComputed(() => props.model.value?.value ?? DEFAULT_OVERVIEW_MODEL);
  const {
    activeCar,
    connectedSensorsText,
    dataFreshnessText,
    recordingStateText,
    runHealth,
    sensorCards,
    strongestSignalText,
  } = useSignalProperties(model, REALTIME_LIVE_OVERVIEW_MODEL_KEYS);
  const labelTexts = labels.value;

  return (
    <>
      <div class="card__header card__header--stack">
        <div>
          <div class="card__title">
            {labelTexts.titleText}
          </div>
          <div class="card__subtle">
            {labelTexts.hintText}
          </div>
        </div>
        <RealtimeLiveOverviewRunHealthPill runHealth={runHealth} />
      </div>
      <div class="stat-grid live-overview__stats">
        <div id="liveConnectedSensors" class="stat">
            <div class="stat__label">
              {labelTexts.connectedSensorsLabel}
            </div>
          <div class="stat__value" data-value>
            {connectedSensorsText}
          </div>
        </div>
        <RealtimeLiveOverviewActiveCarStat activeCar={activeCar} labelText={labelTexts.activeCarLabel} />
        <div id="liveRecordingState" class="stat">
            <div class="stat__label">
              {labelTexts.recordingStateLabel}
            </div>
          <div class="stat__value" data-value>
            {recordingStateText}
          </div>
        </div>
        <div id="liveDataFreshness" class="stat">
            <div class="stat__label">
              {labelTexts.dataFreshnessLabel}
            </div>
          <div class="stat__value" data-value>
            {dataFreshnessText}
          </div>
        </div>
        <div id="liveStrongestSignal" class="stat">
            <div class="stat__label">
              {labelTexts.strongestSignalLabel}
            </div>
          <div class="stat__value" data-value>
            {strongestSignalText}
          </div>
        </div>
        <div class="stat">
            <div class="stat__label">
              {labelTexts.currentSpeedLabel}
            </div>
          <div id="speed" class="stat__value speed" aria-live="polite">
            {props.speedText}
          </div>
        </div>
      </div>
      <div class="live-sensor-roster__header">
        <div class="mini-label">
          {labelTexts.sensorCoverageLabel}
        </div>
      </div>
      <RealtimeLiveOverviewSensorRoster
        sensorCards={sensorCards}
        noSensorsText={labelTexts.noSensorsText}
      />
    </>
  );
}

export function mountRealtimeLiveOverview(
  host: HTMLElement,
  view: RealtimeLiveOverviewBridge,
): void {
  render(<RealtimeLiveOverview model={view.model} speedText={view.speedText} />, host);
}
