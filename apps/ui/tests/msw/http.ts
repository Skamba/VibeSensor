import { HttpResponse, http } from "msw";

export const UI_MSW_ORIGIN = "http://vibesensor.test";

export function uiTestUrl(path: string): string {
  return new URL(path, UI_MSW_ORIGIN).toString();
}

export { http, HttpResponse };
