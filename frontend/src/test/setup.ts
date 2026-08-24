import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});

// Recharts also parks a hidden text-measurement span on document.body that
// cleanup() does not remove, so a bare screen.getByText() in a chart test can
// match it as a phantom duplicate — scope chart queries to `container`.

// Recharts' ResponsiveContainer measures its parent via ResizeObserver, which
// jsdom does not implement.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as never;

// useMediaQuery calls matchMedia during the initial render. jsdom has no
// implementation; default to desktop so ParcelInfo takes its non-mobile path.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("min-width: 768px"),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
