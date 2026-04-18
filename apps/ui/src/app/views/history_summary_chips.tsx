import type { HistoryRowViewModel, HistorySummaryChipTone } from "./history_table_models";

function chipModifier(tone: HistorySummaryChipTone): string {
  switch (tone) {
    case "default":
      return "";
    case "source":
      return " history-row__summary-chip--source";
    default:
      return ` history-row__summary-chip--${tone}`;
  }
}

export function HistorySummaryChips(props: { row: HistoryRowViewModel }) {
  return (
    <div class="history-row__summary-chips">
      {props.row.summaryChips.map((chip) => (
        <span
          key={chip.key}
          class={`history-row__summary-chip${chipModifier(chip.tone)}`}
        >
          {chip.text}
        </span>
      ))}
    </div>
  );
}
