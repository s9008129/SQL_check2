import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
// The dedicated Vitest entry point registers matchers via `expect.extend()`
// using vitest's own `expect` import — unlike the plain package entry, it
// does not assume `expect` is a global (we don't enable vitest's
// `globals`; test files import describe/it/expect explicitly).
import "@testing-library/jest-dom/vitest";

// We don't enable Vitest's `globals` (tests import describe/it/expect
// explicitly so `tsc --noEmit` doesn't depend on ambient global types), so
// @testing-library/react's own auto-cleanup — which only hooks into a
// global `afterEach` — needs a hand here.
afterEach(() => {
  cleanup();
});

// jsdom does not implement ResizeObserver; CodeMirror 6 (used by
// SqlEditor) checks for it when measuring layout. A no-op stub is enough
// for it to mount cleanly in tests.
if (typeof globalThis.ResizeObserver === "undefined") {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}
