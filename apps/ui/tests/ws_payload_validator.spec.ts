import { describe, expect, test } from "vitest";
import { wsPayloadSchema } from "../src/contracts/ws_payload_schema.generated";
import type { LiveWsPayload } from "../src/contracts/ws_payload_types";
import { validateLiveWsPayload } from "../src/ws_payload_validator";

const basePayload: Omit<LiveWsPayload, "spectra"> = {
  schema_version: "1",
  server_time: "2026-01-01T00:00:00Z",
  clients: [
    {
      id: "sensor-1",
      mac_address: "aa:bb:cc:dd:ee:ff",
      name: "Front Left",
      connected: true,
      location_code: "front_left",
      firmware_version: "1.2.3",
      sample_rate_hz: 800,
      last_seen_age_ms: 0,
      frames_total: 10,
      frame_samples: 1024,
      dropped_frames: 0,
    },
  ],
  selected_client_id: null,
  rotational_speeds: null,
  speed_mps: 12.5,
};

function makeStrengthMetrics() {
  return {
    vibration_strength_db: 12,
    peak_amp_g: 0.12,
    noise_floor_amp_g: 0.01,
    strength_bucket: null,
    top_peaks: [
      {
        hz: 120,
        amp: 0.04,
        vibration_strength_db: 12,
        strength_bucket: null,
      },
    ],
  };
}

function makeRepresentativePayload(): LiveWsPayload {
  return {
    ...basePayload,
    selected_client_id: "sensor-1",
    rotational_speeds: {
      basis_speed_source: null,
      wheel: { rpm: 10, mode: null, reason: null },
      driveshaft: { rpm: 20, mode: null, reason: null },
      engine: { rpm: 30, mode: null, reason: null },
      order_bands: [
        {
          key: "1x",
          center_hz: 40,
          tolerance: 0.5,
        },
      ],
    },
    spectra: {
      frame_fingerprint: "sensor-1:0:0:1",
      freq: [10, 20, 30],
      clients: {
        "sensor-1": {
          combined_spectrum_amp_g: [0.1, 0.2, 0.3],
          strength_metrics: makeStrengthMetrics(),
        },
      },
      warning: {
        code: "shared_freq",
        message: "Shared frequency mismatch.",
        client_ids: ["sensor-1"],
      },
      alignment: {
        aligned: true,
        clock_synced: true,
        overlap_ratio: 0.75,
        sensor_count: 1,
        shared_window_s: 0.5,
      },
    },
  };
}

function requiredFields(schema: {
  required?: readonly string[];
}): readonly string[] {
  return schema.required ?? [];
}

type RepresentativePayload = ReturnType<typeof makeRepresentativePayload>;
type DriftBranch = {
  label: string;
  pathPrefix: string;
  required: readonly string[];
  getTarget: (payload: RepresentativePayload) => Record<string, unknown>;
};

const driftBranches: readonly DriftBranch[] = [
  {
    label: "live payload",
    pathPrefix: "",
    required: requiredFields(wsPayloadSchema),
    getTarget: (payload) => payload as unknown as Record<string, unknown>,
  },
  {
    label: "client row",
    pathPrefix: "/clients/0",
    required: requiredFields(wsPayloadSchema.$defs.ClientApiRow),
    getTarget: (payload) =>
      payload.clients[0] as unknown as Record<string, unknown>,
  },
  {
    label: "rotational speeds",
    pathPrefix: "/rotational_speeds",
    required: requiredFields(wsPayloadSchema.$defs.RotationalSpeedsPayload),
    getTarget: (payload) =>
      payload.rotational_speeds as unknown as Record<string, unknown>,
  },
  {
    label: "rotational speed value",
    pathPrefix: "/rotational_speeds/wheel",
    required: requiredFields(wsPayloadSchema.$defs.RotationalSpeedValuePayload),
    getTarget: (payload) =>
      payload.rotational_speeds!.wheel as unknown as Record<string, unknown>,
  },
  {
    label: "order band",
    pathPrefix: "/rotational_speeds/order_bands/0",
    required: requiredFields(wsPayloadSchema.$defs.OrderBandPayload),
    getTarget: (payload) =>
      payload.rotational_speeds!.order_bands![0] as unknown as Record<
        string,
        unknown
      >,
  },
  {
    label: "warning",
    pathPrefix: "/spectra/warning",
    required: requiredFields(wsPayloadSchema.$defs.FrequencyWarningPayload),
    getTarget: (payload) =>
      payload.spectra!.warning as unknown as Record<string, unknown>,
  },
  {
    label: "alignment",
    pathPrefix: "/spectra/alignment",
    required: requiredFields(wsPayloadSchema.$defs.AlignmentInfoPayload),
    getTarget: (payload) =>
      payload.spectra!.alignment as unknown as Record<string, unknown>,
  },
  {
    label: "strength metrics",
    pathPrefix: "/spectra/clients/sensor-1/strength_metrics",
    required: requiredFields(wsPayloadSchema.$defs.VibrationStrengthMetrics),
    getTarget: (payload) =>
      payload.spectra!.clients!["sensor-1"]
        .strength_metrics as unknown as Record<string, unknown>,
  },
  {
    label: "strength peak",
    pathPrefix: "/spectra/clients/sensor-1/strength_metrics/top_peaks/0",
    required: requiredFields(wsPayloadSchema.$defs.StrengthPeak),
    getTarget: (payload) =>
      payload.spectra!.clients!["sensor-1"]!.strength_metrics!
        .top_peaks![0]! as unknown as Record<string, unknown>,
  },
];

const requiredFieldCases = driftBranches.flatMap((branch) =>
  branch.required.map((field) => ({ ...branch, field })),
);

describe("validateLiveWsPayload", () => {
  test("accepts a schema-valid payload", () => {
    expect(
      validateLiveWsPayload({
        ...basePayload,
        spectra: {
          frame_fingerprint: "sensor-1:0:0:1",
          freq: [10, 20, 30],
          clients: {
            "sensor-1": {
              combined_spectrum_amp_g: [0.1, 0.2, 0.3],
              strength_metrics: makeStrengthMetrics(),
            },
          },
        },
      }),
    ).toMatchObject({
      schema_version: "1",
      clients: [{ id: "sensor-1" }],
      spectra: { frame_fingerprint: "sensor-1:0:0:1" },
    });
  });

  test("reports the failing client-row path", () => {
    expect(() =>
      validateLiveWsPayload({
        ...basePayload,
        clients: [
          {
            ...basePayload.clients[0],
            frames_total: "10",
          },
        ],
      }),
    ).toThrow(/Invalid websocket payload: \/clients\/0\/frames_total/);
  });

  test("reports malformed shared spectrum arrays", () => {
    expect(() =>
      validateLiveWsPayload({
        ...basePayload,
        spectra: {
          freq: [10, "bad", 30],
        },
      }),
    ).toThrow(/Invalid websocket payload: \/spectra\/freq/);
  });

  test("reports malformed strength peak fields through Valibot", () => {
    expect(() =>
      validateLiveWsPayload({
        ...basePayload,
        spectra: {
          clients: {
            "sensor-1": {
              combined_spectrum_amp_g: [0.1, 0.2, 0.3],
              strength_metrics: {
                ...makeStrengthMetrics(),
                top_peaks: [
                  {
                    hz: 120,
                    amp: "bad",
                    vibration_strength_db: 12,
                    strength_bucket: null,
                  },
                ],
              },
            },
          },
        },
      }),
    ).toThrow(
      /Invalid websocket payload: \/spectra\/clients\/sensor-1\/strength_metrics\/top_peaks\/0\/amp/,
    );
  });

  test("reports malformed rotational-speed metadata", () => {
    expect(() =>
      validateLiveWsPayload({
        ...basePayload,
        rotational_speeds: {
          basis_speed_source: null,
          wheel: { rpm: 10, mode: null, reason: null },
          driveshaft: { rpm: 20, mode: null, reason: null },
          engine: { rpm: 30, mode: null, reason: null },
          order_bands: [
            {
              key: "1x",
              center_hz: 40,
              tolerance: "wide",
            },
          ],
        },
      }),
    ).toThrow(
      /Invalid websocket payload: \/rotational_speeds\/order_bands\/0\/tolerance/,
    );
  });

  test("reports malformed spectrum frame fingerprint", () => {
    expect(() =>
      validateLiveWsPayload({
        ...basePayload,
        spectra: {
          frame_fingerprint: 123,
        },
      }),
    ).toThrow(/Invalid websocket payload: \/spectra\/frame_fingerprint/);
  });

  test("accepts a representative payload built from schema-driven branches", () => {
    expect(validateLiveWsPayload(makeRepresentativePayload())).toMatchObject({
      clients: [{ id: "sensor-1" }],
      rotational_speeds: {
        order_bands: [{ key: "1x" }],
        wheel: { rpm: 10 },
      },
      selected_client_id: "sensor-1",
      spectra: {
        alignment: { clock_synced: true },
        frame_fingerprint: "sensor-1:0:0:1",
        warning: { code: "shared_freq" },
      },
    });
  });

  test.each(
    requiredFieldCases,
  )("rejects missing schema-derived required $field in $label", ({
    field,
    getTarget,
    pathPrefix,
  }) => {
    const payload = structuredClone(makeRepresentativePayload());
    delete getTarget(payload)[field];
    expect(() => validateLiveWsPayload(payload)).toThrow(
      new RegExp(`Invalid websocket payload: ${pathPrefix}/${field}`),
    );
  });
});
