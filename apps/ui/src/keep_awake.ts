/**
 * Keeps the phone screen on while a run records, so a phone in a holder does
 * not lock mid-drive.
 *
 * The Screen Wake Lock API only exists on secure (https or localhost) pages,
 * and the Pi serves plain http, so the fallback is the NoSleep.js technique: a
 * tiny silent video, muted, inline and looping, started from the Start tap.
 * iOS Safari and Android Chrome do not auto-lock while a video plays. Neither
 * can promise it (iOS Low Power Mode, for one, may still lock), so Live also
 * tells the driver to set auto-lock to Never.
 */
import { signal } from "@preact/signals";

import keepAwakeMp4 from "./assets/keep_awake.mp4?inline";
import keepAwakeWebm from "./assets/keep_awake.webm?inline";

/** How the screen is kept on: a Wake Lock, the muted-video fallback, or not at all. */
export type KeepAwakeMode = "wake-lock" | "video" | "off";

export const keepAwakeMode = signal<KeepAwakeMode>("off");

let wanted = false;
let video: HTMLVideoElement | null = null;
let wakeLock: WakeLockSentinel | null = null;

/**
 * Starts keeping the screen on. Call it straight from the tap that starts a
 * recording: iOS only lets a page start media inside a user gesture.
 */
export function startKeepAwake(): void {
  wanted = true;
  if (keepAwakeMode.peek() === "off") {
    playVideo();
  }
  requestWakeLock();
}

/** Lets the screen lock again. */
export function stopKeepAwake(): void {
  wanted = false;
  video?.pause();
  const lock = wakeLock;
  wakeLock = null;
  void lock?.release().catch(() => undefined);
  keepAwakeMode.value = "off";
}

function playVideo(): void {
  const element = video ?? createVideo();
  if (!element) {
    return;
  }
  keepAwakeMode.value = "video";
  let played: Promise<void> | undefined;
  try {
    played = element.play();
  } catch {
    keepAwakeMode.value = "off";
    return;
  }
  void played?.catch(() => {
    if (keepAwakeMode.peek() === "video") {
      keepAwakeMode.value = "off";
    }
  });
}

function createVideo(): HTMLVideoElement | null {
  if (typeof document === "undefined" || !document.body) {
    return null;
  }
  const element = document.createElement("video");
  element.id = "keepAwakeVideo";
  // Both the properties and the attributes: iOS reads the attributes.
  element.muted = true;
  element.loop = true;
  element.playsInline = true;
  element.setAttribute("muted", "");
  element.setAttribute("playsinline", "");
  element.setAttribute("aria-hidden", "true");
  element.tabIndex = -1;
  // On screen but invisible: WebKit pauses muted videos it considers hidden.
  element.style.cssText =
    "position:fixed;left:0;bottom:0;width:1px;height:1px;opacity:0.01;pointer-events:none;";
  for (const [src, type] of [
    [keepAwakeMp4, "video/mp4"],
    [keepAwakeWebm, "video/webm"],
  ] as const) {
    const source = document.createElement("source");
    source.src = src;
    source.type = type;
    element.append(source);
  }
  // NoSleep's iOS workaround: keep the playhead moving instead of relying on loop alone.
  element.addEventListener("timeupdate", () => {
    if (element.currentTime > 1) {
      element.currentTime = Math.random() * 0.5;
    }
  });
  document.body.append(element);
  video = element;
  return element;
}

function requestWakeLock(): void {
  const api = typeof navigator === "undefined" ? undefined : navigator.wakeLock;
  if (!api || wakeLock) {
    return;
  }
  api.request("screen").then(
    (lock) => {
      if (!wanted) {
        void lock.release().catch(() => undefined);
        return;
      }
      wakeLock = lock;
      video?.pause();
      keepAwakeMode.value = "wake-lock";
      lock.addEventListener("release", () => {
        if (wakeLock === lock) {
          wakeLock = null;
          keepAwakeMode.value = "off";
        }
      });
    },
    () => undefined,
  );
}

// The browser drops a wake lock (and may pause the video) when the page is
// hidden; take it back when the driver returns to the page mid-run.
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (!wanted || document.visibilityState !== "visible") {
      return;
    }
    if (keepAwakeMode.peek() !== "wake-lock") {
      playVideo();
    }
    requestWakeLock();
  });
}
