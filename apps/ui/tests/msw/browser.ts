import type { RequestHandler } from "msw";
import { setupWorker } from "msw/browser";

export function createUiMswWorker(...handlers: RequestHandler[]) {
  return setupWorker(...handlers);
}
