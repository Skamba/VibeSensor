import { expect, test } from "@playwright/test";

import { cloneTransportValue } from "../src/transport/clone";
import type { CarUpsertRequest, CarsPayload } from "../src/transport/http_models";

test("cloneTransportValue clones nested response payloads", () => {
  const transportPayload: CarsPayload = {
    active_car_id: "car-1",
    cars: [
      {
        id: "car-1",
        name: "Daily",
        type: "Coupe",
        variant: "Street",
        aspects: {
          tire_width_mm: 255,
          final_drive_ratio: 3.62,
        },
      },
    ],
  };

  const localPayload = cloneTransportValue(transportPayload);
  localPayload.cars[0].name = "Track";
  localPayload.cars[0].aspects.tire_width_mm = 275;

  expect(transportPayload.cars[0].name).toBe("Daily");
  expect(transportPayload.cars[0].aspects.tire_width_mm).toBe(255);
});

test("cloneTransportValue clones request payloads before boundary serialization", () => {
  const localPayload: CarUpsertRequest = {
    name: "Project Car",
    type: "Sedan",
    aspects: {
      tire_width_mm: 225,
      current_gear_ratio: 0.82,
    },
    variant: "Prototype",
  };

  const transportPayload = cloneTransportValue(localPayload);
  transportPayload.name = "Prototype";
  transportPayload.aspects.current_gear_ratio = 0.71;

  expect(localPayload.name).toBe("Project Car");
  expect(localPayload.aspects.current_gear_ratio).toBe(0.82);
});
