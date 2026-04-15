import { createUiPreactMount } from "../runtime/ui_preact_mount";
import { useUiTranslation } from "../ui_i18n";
import { signal, type ReadonlySignal } from "../ui_signals";

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

interface RealtimeLiveOverviewBridgeState extends RealtimeLiveOverviewRenderModel {
  speedText: string;
}

export interface RealtimeLiveOverviewBridge {
  render(model: RealtimeLiveOverviewRenderModel): void;
  setSpeedText(text: string): void;
}

const DEFAULT_OVERVIEW_STATE: RealtimeLiveOverviewBridgeState = {
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
  speedText: "--",
};

function RealtimeLiveOverview(props: { state: ReadonlySignal<RealtimeLiveOverviewBridgeState> }) {
  const state = props.state.value;
  const t = useUiTranslation();

  return (
    <>
      <div class="card__header card__header--stack">
        <div>
          <div class="card__title">
            {t("dashboard.live_overview", "Live overview")}
          </div>
          <div class="card__subtle">
            {t(
              "dashboard.live_overview_hint",
              "Check readiness, current run state, and the strongest sensor level before reading the chart.",
            )}
          </div>
        </div>
        <div
          id="liveRunHealth"
          class="pill"
          data-variant={state.runHealth.variant}
          hidden={state.runHealth.hidden}
          aria-live="polite"
        >
          {state.runHealth.text}
        </div>
      </div>
      <div class="stat-grid live-overview__stats">
        <div id="liveConnectedSensors" class="stat">
          <div class="stat__label">
            {t("dashboard.connected_sensors", "Sensors online")}
          </div>
          <div class="stat__value" data-value>
            {state.connectedSensorsText}
          </div>
        </div>
        <div
          id="liveActiveCar"
          class="stat"
          data-variant={state.activeCar.warning ? "warn" : undefined}
        >
          <div class="stat__label">
            {t("dashboard.active_car", "Active car")}
          </div>
          <div
            class="stat__value"
            data-value
            data-variant={state.activeCar.warning ? "warn" : undefined}
            data-has-icon={state.activeCar.warning ? "true" : undefined}
          >
            {state.activeCar.warning
              ? (
                <>
                  <span class="stat__value-icon" data-variant="warn" aria-hidden="true">
                    !
                  </span>
                  <span>{state.activeCar.text}</span>
                </>
              )
              : state.activeCar.text}
          </div>
        </div>
        <div id="liveRecordingState" class="stat">
          <div class="stat__label">
            {t("dashboard.recording_state", "Run state")}
          </div>
          <div class="stat__value" data-value>
            {state.recordingStateText}
          </div>
        </div>
        <div id="liveDataFreshness" class="stat">
          <div class="stat__label">
            {t("dashboard.data_freshness", "Feed freshness")}
          </div>
          <div class="stat__value" data-value>
            {state.dataFreshnessText}
          </div>
        </div>
        <div id="liveStrongestSignal" class="stat">
          <div class="stat__label">
            {t("dashboard.strongest_signal", "Strongest signal")}
          </div>
          <div class="stat__value" data-value>
            {state.strongestSignalText}
          </div>
        </div>
        <div class="stat">
          <div class="stat__label">
            {t("dashboard.current_speed", "Current speed")}
          </div>
          <div id="speed" class="stat__value speed" aria-live="polite">
            {state.speedText}
          </div>
        </div>
      </div>
      <div class="live-sensor-roster__header">
        <div class="mini-label">
          {t("dashboard.sensor_coverage", "Sensor coverage")}
        </div>
      </div>
      <div id="liveSensorRoster" class="live-sensor-roster">
        {state.sensorCards.length
          ? state.sensorCards.map((card) => {
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
              {t("settings.sensors.no_sensors", "No sensors yet.")}
            </div>
          )}
      </div>
    </>
  );
}

export function createNullRealtimeLiveOverviewBridge(): RealtimeLiveOverviewBridge {
  return {
    render() {},
    setSpeedText() {},
  };
}

export function mountRealtimeLiveOverview(host: HTMLElement): RealtimeLiveOverviewBridge {
  const mount = createUiPreactMount(host);
  const state = signal<RealtimeLiveOverviewBridgeState>({ ...DEFAULT_OVERVIEW_STATE });
  mount.render(<RealtimeLiveOverview state={state} />);

  return {
    render(model: RealtimeLiveOverviewRenderModel): void {
      state.value = { ...state.value, ...model };
    },
    setSpeedText(text: string): void {
      state.value = { ...state.value, speedText: text };
    },
  };
}
