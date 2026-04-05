import { expect, test } from "@playwright/test";

import { createStatusGridRowElement } from "../src/app/views/dom_helpers";
import { renderInternetStatusPanel } from "../src/app/views/internet_status_view";
import {
  elementChildren,
  FakeHTMLElement,
  installFakeDomGlobals,
  findByClass,
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

test("renderInternetStatusPanel replaces children with a semantic maintenance card", () => {
  const panel = new FakeHTMLElement("DIV");

  renderInternetStatusPanel(panel as unknown as HTMLElement, {
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

  const cards = elementChildren(panel);
  expect(cards).toHaveLength(1);
  expect(cards[0].tagName).toBe("SECTION");
  expect(cards[0].classList.contains("maintenance-card")).toBe(true);

  const title = findByClass(panel, "maintenance-card__title");
  expect(title).toHaveLength(1);
  expect(title[0].textContent).toBe("USB internet");

  const subtle = findByClass(panel, "subtle");
  expect(subtle).toHaveLength(1);
  expect(subtle[0].textContent).toBe("Adapter detected");

  const pills = findByClass(panel, "pill");
  expect(pills).toHaveLength(1);
  expect(pills[0].getAttribute("data-variant")).toBe("warn");
  expect(pills[0].textContent).toBe("Detected");

  const rows = findByClass(panel, "status-grid__row");
  expect(rows).toHaveLength(9);
  expect(rows.map((row) => row.textContent)).toEqual([
    "DetectedYes",
    "UsableNo",
    "Interfaceusb0",
    "ConnectionUSB uplink",
    "Drivercdc_ncm",
    "Addresses192.168.8.2",
    "Gateway192.168.8.1",
    "Default routeYes",
    "DiagnosticRoute ready",
  ]);
  expect(rows[rows.length - 1].textContent).toBe("DiagnosticRoute ready");
});
