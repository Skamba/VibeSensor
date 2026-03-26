import Ajv2020, { type ErrorObject } from "ajv/dist/2020.js";
import type { ValidateFunction } from "ajv";
import wsPayloadSchema from "./contracts/ws_payload_schema.generated";
import type { LiveWsPayload } from "./contracts/ws_payload_types";

const ajv = new Ajv2020({
  allErrors: true,
  strict: false,
});

const liveWsPayloadValidator = ajv.compile(wsPayloadSchema) as ValidateFunction<LiveWsPayload>;
const MAX_FORMATTED_VALIDATION_ERRORS = 3;

function formatValidationErrorSummary(errors: readonly ErrorObject[] | null | undefined): string {
  if (!errors?.length) {
    return "unknown schema violation";
  }
  return errors
    .slice(0, MAX_FORMATTED_VALIDATION_ERRORS)
    .map((error) => {
      const path = error.instancePath || "/";
      return `${path} ${error.message ?? "is invalid"}`;
    })
    .join("; ");
}

export function validateLiveWsPayload(payload: unknown): LiveWsPayload {
  if (liveWsPayloadValidator(payload)) {
    return payload;
  }
  throw new Error(`Invalid websocket payload: ${formatValidationErrorSummary(liveWsPayloadValidator.errors)}`);
}
