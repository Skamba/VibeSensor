import { useUiText } from "../ui_i18n";
import {
  useSignalProperties,
  type ReadonlySignal,
} from "../ui_signals";
import { type DeferredModelSignal, useDeferredModel } from "./view_model_binding";

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

export interface RealtimeLiveOverviewBridge {
  model: DeferredModelSignal<RealtimeLiveOverviewRenderModel>;
  speedText: DeferredModelSignal<string>;
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

const DEFAULT_SPEED_TEXT = "--";

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
  labelText: ReadonlySignal<string>;
}) {
  const { text, warning } = useSignalProperties(props.activeCar, ["text", "warning"] as const);
  const variant = warning.value ? "warn" : undefined;
  const hasIcon = warning.value ? "true" : undefined;

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
  noSensorsText: ReadonlySignal<string>;
}) {
  const sensorCards = props.sensorCards.value;

  return (
    <div id="liveSensorRoster" class="live-sensor-roster">
      {sensorCards.length > 0
        ? sensorCards.map((card) => {
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
                  class="live-sensor-card__status-dot"
                  data-status={statusClass}
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
  speedText: ReadonlySignal<ReadonlySignal<string> | null>;
}) {
  const activeCarLabel = useUiText("dashboard.active_car", "Active car");
  const connectedSensorsLabel = useUiText("dashboard.connected_sensors", "Sensors online");
  const currentSpeedLabel = useUiText("dashboard.current_speed", "Current speed");
  const dataFreshnessLabel = useUiText("dashboard.data_freshness", "Feed freshness");
  const hintText = useUiText(
    "dashboard.live_overview_hint",
    "Check readiness, current run state, and the strongest sensor level before reading the chart.",
  );
  const noSensorsText = useUiText("settings.sensors.no_sensors", "No sensors yet.");
  const recordingStateLabel = useUiText("dashboard.recording_state", "Run state");
  const sensorCoverageLabel = useUiText("dashboard.sensor_coverage", "Sensor coverage");
  const strongestSignalLabel = useUiText("dashboard.strongest_signal", "Strongest signal");
  const titleText = useUiText("dashboard.live_overview", "Live overview");
  const model = useDeferredModel(props.model, DEFAULT_OVERVIEW_MODEL);
  const speedText = useDeferredModel(props.speedText, DEFAULT_SPEED_TEXT);
  const {
    activeCar,
    connectedSensorsText,
    dataFreshnessText,
    recordingStateText,
    runHealth,
    sensorCards,
    strongestSignalText,
  } = useSignalProperties(model, REALTIME_LIVE_OVERVIEW_MODEL_KEYS);
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
        <RealtimeLiveOverviewRunHealthPill runHealth={runHealth} />
      </div>
      <div class="stat-grid live-overview__stats">
        <div id="liveConnectedSensors" class="stat">
            <div class="stat__label">
              {connectedSensorsLabel}
            </div>
          <div class="stat__value" data-value>
            {connectedSensorsText}
          </div>
        </div>
        <RealtimeLiveOverviewActiveCarStat activeCar={activeCar} labelText={activeCarLabel} />
        <div id="liveRecordingState" class="stat">
            <div class="stat__label">
              {recordingStateLabel}
            </div>
          <div class="stat__value" data-value>
            {recordingStateText}
          </div>
        </div>
        <div id="liveDataFreshness" class="stat">
            <div class="stat__label">
              {dataFreshnessLabel}
            </div>
          <div class="stat__value" data-value>
            {dataFreshnessText}
          </div>
        </div>
        <div id="liveStrongestSignal" class="stat">
            <div class="stat__label">
              {strongestSignalLabel}
            </div>
          <div class="stat__value" data-value>
            {strongestSignalText}
          </div>
        </div>
        <div class="stat">
            <div class="stat__label">
              {currentSpeedLabel}
            </div>
          <div id="speed" class="stat__value speed" aria-live="polite">
            {speedText}
          </div>
        </div>
      </div>
      <div class="live-sensor-roster__header">
        <div class="mini-label">
          {sensorCoverageLabel}
        </div>
      </div>
      <RealtimeLiveOverviewSensorRoster
        sensorCards={sensorCards}
        noSensorsText={noSensorsText}
      />
    </>
  );
}

export function RealtimeLiveOverviewPanel(props: {
  view: RealtimeLiveOverviewBridge;
}) {
  return <RealtimeLiveOverview model={props.view.model} speedText={props.view.speedText} />;
}
