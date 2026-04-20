import { expect, test } from "vitest";
import { buildInternetStatusPanelModel } from "../src/app/views/internet_status_view";
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
