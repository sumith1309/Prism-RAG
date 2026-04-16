import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// Reset the DOM + mocks between tests so one test's side effects don't
// leak into the next one. RTL's cleanup() unmounts any surviving
// component trees and removes event listeners.
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// Silence the noisy "Not implemented: window.scrollTo" jsdom warning
// triggered by framer-motion when it enters a new page.
Object.defineProperty(window, "scrollTo", { value: () => {}, writable: true });

// Match-media polyfill — some of our components probe this for responsive
// rendering (mostly from the Tailwind arbitrary variants we use).
if (typeof window.matchMedia === "undefined") {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}
