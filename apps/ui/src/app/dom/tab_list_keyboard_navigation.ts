import type { JSX } from "preact";

export function normalizeTabListIndex(index: number, count: number): number {
  if (count <= 0) {
    return 0;
  }
  return ((index % count) + count) % count;
}

export function handleTabListKeyboardNavigation<TTabId>(props: {
  count: number;
  event: JSX.TargetedKeyboardEvent<HTMLButtonElement>;
  focusTabAt(index: number): void;
  getTabIdAt(index: number): TTabId;
  index: number;
  onActivateTab(tabId: TTabId): void;
}): void {
  const { count, event, focusTabAt, getTabIdAt, index, onActivateTab } = props;
  if (count <= 0) {
    return;
  }

  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    onActivateTab(getTabIdAt(index));
    return;
  }

  let nextIndex: number | null = null;
  if (event.key === "ArrowRight") {
    nextIndex = normalizeTabListIndex(index + 1, count);
  } else if (event.key === "ArrowLeft") {
    nextIndex = normalizeTabListIndex(index - 1, count);
  } else if (event.key === "Home") {
    nextIndex = 0;
  } else if (event.key === "End") {
    nextIndex = count - 1;
  }

  if (nextIndex === null) {
    return;
  }

  event.preventDefault();
  onActivateTab(getTabIdAt(nextIndex));
  focusTabAt(nextIndex);
}
