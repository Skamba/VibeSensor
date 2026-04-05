export type ViewDisposer = () => void;

const NOOP_VIEW_DISPOSER: ViewDisposer = () => undefined;

type BindableEventTarget = Pick<EventTarget, "addEventListener" | "removeEventListener">;

export function bindViewEvent<TEvent extends Event>(
  target: BindableEventTarget | null | undefined,
  type: string,
  listener: (event: TEvent) => void,
): ViewDisposer {
  if (!target) {
    return NOOP_VIEW_DISPOSER;
  }
  const wrappedListener: EventListener = (event) => {
    listener(event as TEvent);
  };
  target.addEventListener(type, wrappedListener);
  return () => {
    target.removeEventListener(type, wrappedListener);
  };
}

export function composeViewDisposers(...disposers: readonly ViewDisposer[]): ViewDisposer {
  return () => {
    for (const dispose of disposers) {
      dispose();
    }
  };
}
