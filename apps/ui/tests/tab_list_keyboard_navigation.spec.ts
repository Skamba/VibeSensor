import { describe, expect, test } from "vitest";
import type { JSX } from "preact";

import {
  handleTabListKeyboardNavigation,
  normalizeTabListIndex,
} from "../src/app/dom/tab_list_keyboard_navigation";

function makeKeyboardEvent(key: string): {
  event: JSX.TargetedKeyboardEvent<HTMLButtonElement>;
  wasPrevented: () => boolean;
} {
  let prevented = false;
  return {
    event: {
      key,
      preventDefault() {
        prevented = true;
      },
    } as unknown as JSX.TargetedKeyboardEvent<HTMLButtonElement>,
    wasPrevented: () => prevented,
  };
}

describe("tab_list_keyboard_navigation", () => {
  test("normalizes and focuses wrapped arrow navigation targets", () => {
    const activated: string[] = [];
    const focused: number[] = [];
    const { event, wasPrevented } = makeKeyboardEvent("ArrowLeft");

    expect(normalizeTabListIndex(3, 3)).toBe(0);
    expect(normalizeTabListIndex(-1, 3)).toBe(2);
    expect(normalizeTabListIndex(0, 0)).toBe(0);

    handleTabListKeyboardNavigation({
      count: 3,
      event,
      focusTabAt: (index) => focused.push(index),
      getTabIdAt: (index) => ["live", "history", "settings"][index] ?? "",
      index: 0,
      onActivateTab: (tabId) => activated.push(tabId),
    });

    expect(wasPrevented()).toBe(true);
    expect(activated).toEqual(["settings"]);
    expect(focused).toEqual([2]);
  });

  test("activates current tab on enter and space without moving focus", () => {
    for (const key of ["Enter", " "]) {
      const activated: string[] = [];
      const focused: number[] = [];
      const { event, wasPrevented } = makeKeyboardEvent(key);

      handleTabListKeyboardNavigation({
        count: 3,
        event,
        focusTabAt: (index) => focused.push(index),
        getTabIdAt: (index) => ["live", "history", "settings"][index] ?? "",
        index: 1,
        onActivateTab: (tabId) => activated.push(tabId),
      });

      expect(wasPrevented()).toBe(true);
      expect(activated).toEqual(["history"]);
      expect(focused).toEqual([]);
    }
  });
});
