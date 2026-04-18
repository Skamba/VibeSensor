import type { JSX } from "preact";

import type { HistoryHeatmapViewModel } from "./history_table_models";

type HistoryHeatmapZoneStyle = JSX.CSSProperties & {
  "--history-heatmap-accent"?: string;
  "--history-heatmap-fill"?: string;
};

function heatmapZoneStyle(zone: HistoryHeatmapViewModel["zones"][number]): HistoryHeatmapZoneStyle {
  const style: HistoryHeatmapZoneStyle = {
    gridArea: zone.gridArea,
  };
  if (zone.valueLabel !== null && zone.accentColor !== null && zone.fillPercent !== null) {
    style["--history-heatmap-accent"] = zone.accentColor;
    style["--history-heatmap-fill"] = `${zone.fillPercent}%`;
  }
  return style;
}

export function HistoryHeatmap(props: { heatmap: HistoryHeatmapViewModel }) {
  const { heatmap } = props;
  return (
    <div class="history-heatmap">
      <div class="history-heatmap__header">
        <div class="history-heatmap__title">{heatmap.title}</div>
      </div>
      {heatmap.stateMessage ? (
        <p class={heatmap.stateTone === "error" ? "history-inline-error" : "subtle"}>
          {heatmap.stateMessage}
        </p>
      ) : (
        <>
          <div class="history-heatmap__grid">
            {heatmap.zones.map((zone) => {
              const isEmpty =
                zone.valueLabel === null
                || zone.accentColor === null
                || zone.fillPercent === null;
              return (
                <div
                  key={zone.key}
                  class={[
                    "history-heatmap__zone",
                    isEmpty ? "history-heatmap__zone--empty" : "",
                    !isEmpty && zone.strongest ? "history-heatmap__zone--strongest" : "",
                  ].filter(Boolean).join(" ")}
                  style={heatmapZoneStyle(zone)}
                  title={isEmpty ? zone.label : `${zone.label}: ${zone.valueLabel}`}
                  data-location-key={zone.key}
                >
                  <div class="history-heatmap__zone-label">{zone.label}</div>
                  <div
                    class={[
                      "history-heatmap__zone-value",
                      isEmpty ? "history-heatmap__zone-value--empty" : "",
                    ].filter(Boolean).join(" ")}
                  >
                    {zone.valueLabel ?? ""}
                  </div>
                  <div class="history-heatmap__zone-meter" aria-hidden="true">
                    {!isEmpty ? <span class="history-heatmap__zone-meter-fill" /> : null}
                  </div>
                </div>
              );
            })}
          </div>
          {heatmap.extras.length ? (
            <div class="history-heatmap__extras">
              {heatmap.extras.map((extra, index) => (
                <div key={`${extra}:${index}`} class="history-heatmap__extra-chip">
                  {extra}
                </div>
              ))}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
