import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

type KeepAwake = typeof import("../src/keep_awake");

/** A fresh module per test: it keeps its video and wake lock at module level. */
async function load(): Promise<KeepAwake> {
  vi.resetModules();
  return await import("../src/keep_awake");
}

function video(): HTMLVideoElement | null {
  return document.querySelector<HTMLVideoElement>("#keepAwakeVideo");
}

function showPage(): void {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => "visible",
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

class FakeWakeLock extends EventTarget {
  released = false;
  async release(): Promise<void> {
    this.released = true;
    this.dispatchEvent(new Event("release"));
  }
}

describe("keep awake", () => {
  let play: ReturnType<typeof vi.fn<() => Promise<void>>>;
  let pause: ReturnType<typeof vi.fn<() => void>>;

  beforeEach(() => {
    document.body.innerHTML = "";
    play = vi.fn<() => Promise<void>>(() => Promise.resolve());
    pause = vi.fn<() => void>();
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(play);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(pause);
    Reflect.deleteProperty(navigator, "wakeLock");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    Reflect.deleteProperty(navigator, "wakeLock");
    Reflect.deleteProperty(document, "visibilityState");
  });

  test("over plain http, the Start tap plays a muted inline looping video until stop", async () => {
    const keepAwake = await load();
    keepAwake.startKeepAwake();

    const element = video();
    expect(element).not.toBeNull();
    expect(element?.muted).toBe(true);
    expect(element?.loop).toBe(true);
    expect(element?.hasAttribute("playsinline")).toBe(true);
    expect(
      [...(element?.querySelectorAll("source") ?? [])].map((s) => s.type),
    ).toEqual(["video/mp4", "video/webm"]);
    expect(element?.querySelector("source")?.getAttribute("src")).toMatch(
      /^data:video\/mp4;base64,/,
    );
    expect(play).toHaveBeenCalledTimes(1);
    expect(keepAwake.keepAwakeMode.value).toBe("video");

    // A second start (status poll after the tap) neither replays nor adds a video.
    keepAwake.startKeepAwake();
    expect(play).toHaveBeenCalledTimes(1);
    expect(document.querySelectorAll("video")).toHaveLength(1);

    keepAwake.stopKeepAwake();
    expect(pause).toHaveBeenCalled();
    expect(keepAwake.keepAwakeMode.value).toBe("off");

    // Coming back to the page after the run does not restart it.
    showPage();
    expect(play).toHaveBeenCalledTimes(1);
  });

  test("a refused play leaves the screen unguarded and says so", async () => {
    play.mockImplementation(() => Promise.reject(new Error("NotAllowed")));
    const keepAwake = await load();
    keepAwake.startKeepAwake();
    await Promise.resolve();
    await Promise.resolve();
    expect(keepAwake.keepAwakeMode.value).toBe("off");
    keepAwake.stopKeepAwake();
  });

  test("a wake lock replaces the video where the page may hold one", async () => {
    const lock = new FakeWakeLock();
    const request = vi.fn(() => Promise.resolve(lock));
    Object.defineProperty(navigator, "wakeLock", {
      configurable: true,
      value: { request },
    });
    const keepAwake = await load();
    keepAwake.startKeepAwake();
    await vi.waitFor(() =>
      expect(keepAwake.keepAwakeMode.value).toBe("wake-lock"),
    );
    expect(request).toHaveBeenCalledWith("screen");
    expect(pause).toHaveBeenCalled();

    keepAwake.stopKeepAwake();
    expect(lock.released).toBe(true);
    expect(keepAwake.keepAwakeMode.value).toBe("off");
  });

  test("returning to the page mid-run takes the screen back", async () => {
    const keepAwake = await load();
    keepAwake.startKeepAwake();
    expect(play).toHaveBeenCalledTimes(1);
    showPage();
    expect(play).toHaveBeenCalledTimes(2);
    keepAwake.stopKeepAwake();
  });
});
