import { expect, test } from "@playwright/test";

import { createStatusGridRowElement } from "../src/app/views/dom_helpers";
import { buildInternetStatusPanelModel } from "../src/app/views/internet_status_view";
import {
  elementChildren,
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

test("createStatusGridRowElement builds semantic label and value nodes", () => {
  const row = createStatusGridRowElement("Detected", "Yes") as unknown as FakeElement;

  expect(row.tagName).toBe("DIV");
  expect(row.classList.contains("status-grid__row")).toBe(true);

  const spans = elementChildren(row);
  expect(spans).toHaveLength(2);
  expect(spans[0].tagName).toBe("SPAN");
  expect(spans[0].classList.contains("status-grid__label")).toBe(true);
  expect(spans[0].textContent).toBe("Detected");
  expect(spans[1].tagName).toBe("SPAN");
  expect(spans[1].textContent).toBe("Yes");
});

test("buildInternetStatusPanelModel returns semantic badge and status rows", () => {
  const model = buildInternetStatusPanelModel({
    detected: true,
    usable: false,
    interface_name: "usb0",
    connection_name: "USB uplink",
    driver: "cdc_ncm",
    ipv4_addresses: ["192.168.8.2"],
    gateway: "192.168.8.1",
    has_default_route: true,
    diagnostic: "Route ready",
  }, {
    t: (key) => ({
      "settings.internet.card_title": "USB internet",
      "settings.internet.state.usable": "Usable",
      "settings.internet.state.detected": "Detected",
      "settings.internet.state.not_detected": "Not detected",
      "settings.internet.summary.usable": "USB internet ready",
      "settings.internet.summary.detected": "Adapter detected",
      "settings.internet.summary.not_detected": "No adapter detected",
      "settings.internet.detected": "Detected",
      "settings.internet.usable": "Usable",
      "settings.internet.bool.yes": "Yes",
      "settings.internet.bool.no": "No",
      "settings.internet.interface": "Interface",
      "settings.internet.connection": "Connection",
      "settings.internet.driver": "Driver",
      "settings.internet.addresses": "Addresses",
      "settings.internet.gateway": "Gateway",
      "settings.internet.default_route": "Default route",
      "settings.internet.diagnostic": "Diagnostic",
    })[key] ?? key,
  });

  expect(model.titleText).toBe("USB internet");
  expect(model.summaryText).toBe("Adapter detected");
  expect(model.badge).toEqual({
    variant: "warn",
    text: "Detected",
  });
  expect(model.rows).toEqual([
    { labelText: "Detected", valueText: "Yes" },
    { labelText: "Usable", valueText: "No" },
    { labelText: "Interface", valueText: "usb0" },
    { labelText: "Connection", valueText: "USB uplink" },
    { labelText: "Driver", valueText: "cdc_ncm" },
    { labelText: "Addresses", valueText: "192.168.8.2" },
    { labelText: "Gateway", valueText: "192.168.8.1" },
    { labelText: "Default route", valueText: "Yes" },
    { labelText: "Diagnostic", valueText: "Route ready" },
  ]);
});
