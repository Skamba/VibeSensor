import {
  CAPABILITY_FAMILIES,
  CAPABILITY_MARK_SYMBOL,
  type Capabilities,
  capabilityFamilyKey,
  capabilityMark,
  capabilityNoteKey,
  type FuelType,
} from "../../capabilities";
import type { ProvenanceTier } from "../../car_references";
import { t } from "../../i18n";

/** What a car's references let a run test, one line per order family. */
export function CapabilityList(props: {
  capabilities: Capabilities;
  fuelType: FuelType;
  compact?: boolean;
  id?: string;
}) {
  return (
    <ul
      id={props.id}
      class={
        props.compact
          ? "car-capabilities car-capabilities--compact"
          : "car-capabilities"
      }
    >
      {CAPABILITY_FAMILIES.map((family) => {
        const value = props.capabilities[family];
        const mark = capabilityMark(value);
        const noteKey = capabilityNoteKey(family, value);
        return (
          <li key={family} data-family={family} data-mark={mark}>
            <span
              class="car-capabilities__mark"
              role="img"
              aria-label={t(`capabilities.mark.${mark}`)}
            >
              {CAPABILITY_MARK_SYMBOL[mark]}
            </span>
            <span class="car-capabilities__text">
              <strong>{t(capabilityFamilyKey(family, props.fuelType))}</strong>
              {noteKey ? (
                <span class="car-capabilities__note">{t(noteKey)}</span>
              ) : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** A provenance chip: exact, checked, estimate, yours or unknown. */
export function ProvenanceChip(props: { tier: ProvenanceTier }) {
  return (
    <span class="ref-chip" data-tier={props.tier}>
      {t(`settings.car.tier.${props.tier}`)}
    </span>
  );
}
