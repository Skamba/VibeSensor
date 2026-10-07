import { Note, Pill, type Variant } from "../../components/maintenance";
import { t } from "../../i18n";
import { liveSensorLayout } from "../../live_store";
import { layoutConsequence } from "../../sensor_layout";
import { activeCar } from "../../settings_store";
import {
  type Placement,
  type PlacementSensor,
  placesOnTap,
  SPOTS,
  type Spot,
  sensorTitle,
  spotLabel,
} from "./placement_model";
import {
  identify,
  openFirmwareUpdate,
  outdatedFirmwareCount,
  placement,
  placing,
  remove,
  select,
  tapSpot,
  unplace,
} from "./sensors_store";

type FirmwareStatus = PlacementSensor["firmwareStatus"];

const FIRMWARE_STATUS_VARIANT: Record<FirmwareStatus, Variant> = {
  current: "ok",
  outdated: "warn",
  unknown: "muted",
};

function FirmwareInfo(props: { version: string; status: FirmwareStatus }) {
  return (
    <span class="sensor-firmware" data-firmware-status={props.status}>
      <span>
        {props.version
          ? t("settings.sensors.firmware.version", { version: props.version })
          : t("settings.sensors.firmware.unreported")}
      </span>
      <Pill variant={FIRMWARE_STATUS_VARIANT[props.status]}>
        {t(`settings.sensors.firmware.status.${props.status}`)}
      </Pill>
    </span>
  );
}

/** Shown while any sensor runs older firmware than this Pi flashes. */
function FirmwareUpdateNotice() {
  const count = outdatedFirmwareCount.value;
  if (count === 0) {
    return null;
  }
  return (
    <div id="sensorFirmwareNotice">
      <Note>
        <strong>
          {count === 1
            ? t("settings.sensors.firmware.notice_one")
            : t("settings.sensors.firmware.notice_many", { count })}
        </strong>{" "}
        {t("settings.sensors.firmware.usb_required")}
        <div class="maintenance-action-row">
          <button
            type="button"
            id="sensorFirmwareUpdateBtn"
            class="btn"
            onClick={openFirmwareUpdate}
          >
            {t("settings.sensors.firmware.update")}
          </button>
        </div>
      </Note>
    </div>
  );
}

function StatusDot(props: { connected: boolean }) {
  return (
    <span
      class="sensor-status-dot"
      data-status={props.connected ? "online" : "offline"}
      aria-hidden="true"
    />
  );
}

/** "3 sensors to place": one chip per unplaced sensor. */
function UnplacedSensors(props: { model: Placement }) {
  const { unplaced, selected } = props.model;
  return (
    <div class="sensor-to-place">
      <div id="sensorsToPlace" class="sensor-to-place__title">
        {unplaced.length === 0
          ? t("settings.sensors.all_placed")
          : t("settings.sensors.to_place", { count: unplaced.length })}
      </div>
      {unplaced.length > 0 ? (
        <ul class="sensor-chips" aria-labelledby="sensorsToPlace">
          {unplaced.map((sensor) => {
            const status = t(
              sensor.connected ? "status.online" : "status.offline",
            );
            return (
              <li key={sensor.id}>
                <button
                  type="button"
                  class="sensor-chip"
                  data-client-id={sensor.id}
                  aria-pressed={selected?.id === sensor.id}
                  aria-label={`${sensorTitle(sensor)}, ${status}`}
                  onClick={() => select(sensor.id)}
                >
                  <StatusDot connected={sensor.connected} />
                  <span>{sensorTitle(sensor)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

/** The selected sensor: where it goes, Identify, and the rarer actions. */
function SelectedSensor(props: { model: Placement }) {
  const sensor = props.model.selected;
  if (!sensor) {
    return (
      <p id="sensorSelection" class="sensor-selection__hint">
        {t("settings.sensors.select_hint")}
      </p>
    );
  }
  const location = sensor.code ? t(`location.${sensor.code}`) : "";
  return (
    <section
      id="sensorSelection"
      class="sensor-selection"
      data-client-id={sensor.id}
      aria-labelledby="sensorSelectionTitle"
    >
      <div class="sensor-selection__head">
        <strong id="sensorSelectionTitle">
          {location ? `${location} · ${sensor.shortId}` : sensorTitle(sensor)}
        </strong>
        <span
          class="status-pill settings-entity-status"
          data-status={sensor.connected ? "online" : "offline"}
        >
          {t(sensor.connected ? "status.online" : "status.offline")}
        </span>
      </div>
      <div class="sensor-selection__meta">
        <code>{sensor.mac}</code>
        <FirmwareInfo
          version={sensor.firmwareVersion}
          status={sensor.firmwareStatus}
        />
      </div>
      <p class="sensor-selection__hint">
        {location
          ? t("settings.sensors.move_hint")
          : t("settings.sensors.place_hint")}
      </p>
      <div class="sensor-selection__actions">
        <button
          type="button"
          class="btn btn--primary sensor-identify"
          disabled={!sensor.connected}
          onClick={() => void identify(sensor.id)}
        >
          {t("actions.identify")}
        </button>
        {location ? (
          <button
            type="button"
            class="btn sensor-unplace"
            disabled={placing.value}
            onClick={() => void unplace(sensor.id)}
          >
            {t("settings.sensors.unplace")}
          </button>
        ) : null}
        <button
          type="button"
          class="btn sensor-done"
          onClick={() => select(null)}
        >
          {t("settings.sensors.done")}
        </button>
      </div>
      <details class="sensor-more">
        <summary class="sensor-more__summary">
          {t("settings.sensors.more")}
        </summary>
        <button
          type="button"
          class="btn btn--danger-quiet sensor-remove"
          onClick={() => void remove(sensor.id)}
        >
          {t("settings.sensors.remove")}
        </button>
      </details>
    </section>
  );
}

function spotName(
  spot: Spot,
  occupant: PlacementSensor | undefined,
  model: Placement,
): string {
  const location = t(`location.${spot.code}`);
  const { selected } = model;
  if (selected && placesOnTap(model, occupant)) {
    const sensor = sensorTitle(selected);
    return occupant
      ? t("settings.sensors.spot_aria.replace", {
          location,
          sensor,
          occupant: occupant.shortId,
        })
      : t("settings.sensors.spot_aria.place", { location, sensor });
  }
  if (!occupant) {
    return t("settings.sensors.spot_aria.empty", { location });
  }
  return occupant.id === selected?.id
    ? t("settings.sensors.spot_aria.selected", {
        location,
        sensor: occupant.shortId,
      })
    : t("settings.sensors.spot_aria.occupied", {
        location,
        sensor: occupant.shortId,
        status: t(occupant.connected ? "status.online" : "status.offline"),
      });
}

function SpotButton(props: { spot: Spot; model: Placement }) {
  const { spot, model } = props;
  const occupant = model.byCode.get(spot.code);
  const places = placesOnTap(model, occupant);
  return (
    <button
      type="button"
      class="car-spot"
      data-code={spot.code}
      data-kind={spot.wheel ? "wheel" : "zone"}
      data-client-id={occupant?.id}
      data-target={places ? "true" : undefined}
      aria-pressed={occupant ? occupant.id === model.selected?.id : undefined}
      aria-label={spotName(spot, occupant, model)}
      disabled={(!places && !occupant) || placing.value}
      style={{
        gridRow: String(spot.row),
        gridColumn: `${spot.col} / span ${spot.span}`,
      }}
      onClick={() => void tapSpot(spot.code)}
    >
      <span class="car-spot__label">{spotLabel(spot.code, t)}</span>
      {occupant ? (
        <span class="car-spot__sensor">
          <StatusDot connected={occupant.connected} />
          {occupant.shortId}
        </span>
      ) : null}
    </button>
  );
}

/** A top-down car with every mounting spot as a button, front at the top. */
function CarDiagram(props: { model: Placement }) {
  return (
    <fieldset
      id="sensorCarDiagram"
      class="car-diagram"
      aria-label={t("settings.sensors.diagram_label")}
    >
      <div class="car-diagram__front" aria-hidden="true">
        {t("settings.sensors.front")}
      </div>
      <div class="car-diagram__grid">
        <div class="car-diagram__body" aria-hidden="true" />
        {SPOTS.map((spot) => (
          <SpotButton key={spot.code} spot={spot} model={props.model} />
        ))}
      </div>
    </fieldset>
  );
}

const RECOMMENDED_LAYOUTS = [
  "four_wheels_cabin",
  "four_wheels",
  "cabin_only",
  "single",
] as const;
const MOUNTING_RULES = ["rigid", "firm", "clear", "identify"] as const;

/** Where to mount the sensors, and what the current layout can localise. */
function MountingGuide(props: { placed: boolean }) {
  const layout = liveSensorLayout.value;
  const fuelType = activeCar.value?.fuel_type ?? null;
  return (
    <details
      id="sensorMountingGuide"
      class="settings-help-disclosure sensor-mounting-guide"
      open={!props.placed}
    >
      <summary class="settings-help-disclosure__summary">
        <span class="settings-help-disclosure__heading">
          <span class="settings-help-disclosure__title">
            {t("settings.sensors.mounting.title")}
          </span>
          <span
            id="sensorLayoutConsequence"
            class="settings-help-disclosure__caption"
          >
            {layout
              ? layoutConsequence(layout, fuelType, t)
              : t("settings.sensors.mounting.no_layout")}
          </span>
        </span>
      </summary>
      <div class="settings-help-disclosure__body">
        <div class="mini-label">
          {t("settings.sensors.mounting.layouts_title")}
        </div>
        <ul class="sensor-mounting-guide__list">
          {RECOMMENDED_LAYOUTS.map((key) => (
            <li key={key}>
              {t(
                `settings.sensors.mounting.layout.${key}${
                  key === "cabin_only" && fuelType === "EV" ? "_ev" : ""
                }`,
              )}
            </li>
          ))}
        </ul>
        <div class="mini-label">
          {t("settings.sensors.mounting.rules_title")}
        </div>
        <ul class="sensor-mounting-guide__list">
          {MOUNTING_RULES.map((key) => (
            <li key={key}>{t(`settings.sensors.mounting.rule.${key}`)}</li>
          ))}
        </ul>
      </div>
    </details>
  );
}

/** Settings > Sensors: place each sensor on the car, identify or remove it. */
export function Sensors() {
  const model = placement.value;
  return (
    <>
      <div class="panel card">
        <strong>{t("settings.sensors.title")}</strong>
        <div class="subtle">{t("settings.sensors.hint")}</div>
        <FirmwareUpdateNotice />
        <div class="sensor-placement">
          <div class="sensor-placement__side">
            {model.sensors.length === 0 ? (
              <p id="sensorsEmpty" class="sensor-placement__empty">
                {t("settings.sensors.no_sensors")}
              </p>
            ) : (
              <>
                <UnplacedSensors model={model} />
                <SelectedSensor model={model} />
              </>
            )}
          </div>
          <CarDiagram model={model} />
        </div>
      </div>
      <MountingGuide placed={model.byCode.size > 0} />
    </>
  );
}
