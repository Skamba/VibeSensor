import { render, type ComponentChildren } from "preact";

export interface UiPreactMount {
  readonly host: Element;
  readonly isDisposed: boolean;
  render(content: ComponentChildren): void;
  dispose(): void;
}

export function createUiPreactMount(host: Element): UiPreactMount {
  let disposed = false;

  return {
    host,
    get isDisposed(): boolean {
      return disposed;
    },
    render(content: ComponentChildren): void {
      if (disposed) {
        throw new Error("Cannot render into a disposed Preact mount.");
      }
      render(content, host);
    },
    dispose(): void {
      if (disposed) {
        return;
      }
      disposed = true;
      render(null, host);
    },
  };
}

