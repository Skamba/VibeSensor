import { expect, test } from "@playwright/test";

import { createUpdateLogCard } from "../src/app/views/update_status_log_view";
import {
  createUpdateCurrentStatusCard,
  createUpdateJourneyCard,
} from "../src/app/views/update_status_overview_view";
import {
  findByClass,
  installFakeDomGlobals,
} from "./dom_render_test_support";
import type { FakeElement } from "./dom_render_test_support";

let restoreDom = () => undefined;

test.beforeEach(() => {
  restoreDom = installFakeDomGlobals();
});

test.afterEach(() => {
  restoreDom();
  restoreDom = () => undefined;
});

test("createUpdateCurrentStatusCard renders badge and empty note from typed input", () => {
  const card = createUpdateCurrentStatusCard({
    titleText: "Current status",
    summaryText: "Ready to start",
    badge: {
      variant: "ok",
      text: "Ready",
    },
    rows: [],
    emptyText: "No updater activity yet.",
  }) as unknown as FakeElement;

  expect(card.tagName).toBe("SECTION");
  expect(findByClass(card, "maintenance-card__title")[0].textContent).toBe("Current status");
  expect(findByClass(card, "subtle")[0].textContent).toBe("Ready to start");
  expect(findByClass(card, "pill")[0].textContent).toBe("Ready");
  expect(findByClass(card, "pill")[0].classList.contains("pill--ok")).toBe(true);
  expect(findByClass(card, "maintenance-note")[0].textContent).toBe("No updater activity yet.");
});

test("createUpdateJourneyCard renders typed failure guidance and stage metadata", () => {
  const card = createUpdateJourneyCard({
    titleText: "Update journey",
    subtitleText: "Follow each stage",
    failureNote: {
      summaryText: "restoring_hotspot — Hotspot restart timed out",
      detailText: "NetworkManager is still reconnecting to the uplink.",
      recoveryTitleText: "Retry hotspot recovery",
      recoveryDetailText: "Reconnect the uplink and retry.",
    },
    stages: [
      {
        phase: "validating",
        titleText: "Validating",
        detailText: "Confirming prerequisites",
        markerText: "✓",
        state: "done",
        stateText: "Done",
        current: false,
      },
      {
        phase: "restoring_hotspot",
        titleText: "Restoring hotspot",
        detailText: "Bringing the hotspot back",
        markerText: "7",
        state: "attention",
        stateText: "Needs attention",
        current: false,
      },
    ],
  }) as unknown as FakeElement;

  const stages = findByClass(card, "maintenance-stage");
  expect(stages).toHaveLength(2);
  expect(stages[1].getAttribute("data-stage-phase")).toBe("restoring_hotspot");
  expect(stages[1].getAttribute("data-stage-state")).toBe("attention");
  expect(stages[1].getAttribute("aria-current")).toBeNull();
  expect(findByClass(card, "maintenance-note--bad")[0].textContent)
    .toContain("Hotspot restart timed out");
  expect(findByClass(card, "issue-detail")[0].textContent)
    .toBe("NetworkManager is still reconnecting to the uplink.");
});

test("createUpdateLogCard renders live note and preformatted lines from typed input", () => {
  const card = createUpdateLogCard({
    titleText: "Updater log",
    subtitleText: "Streaming live output",
    noteText: "New lines appear here while the updater is running.",
    lines: ["line 1", "line 2"],
    emptyState: null,
  }) as unknown as FakeElement;

  expect(findByClass(card, "maintenance-card__title")[0].textContent).toBe("Updater log");
  expect(findByClass(card, "maintenance-note")[0].textContent)
    .toBe("New lines appear here while the updater is running.");
  expect(findByClass(card, "log-pre")[0].textContent).toBe("line 1\nline 2\n");
});
