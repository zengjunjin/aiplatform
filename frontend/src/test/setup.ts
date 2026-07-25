import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
});

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => {},
  }),
});

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

(globalThis as any).ResizeObserver = ResizeObserverMock;

vi.stubGlobal('ResizeObserver', ResizeObserverMock);

// IntersectionObserver mock (jsdom 不实现, 但 ChatPage 流式滚动依赖它)
// eslint-disable-next-line no-undef
type IOCallback = IntersectionObserverCallback;
class IntersectionObserverMock {
  callback: IOCallback;
  targets: Element[] = [];
  constructor(callback: IOCallback) {
    this.callback = callback;
  }
  observe(target: Element) {
    this.targets.push(target);
  }
  unobserve(target: Element) {
    this.targets = this.targets.filter((t) => t !== target);
  }
  disconnect() {
    this.targets = [];
  }
  takeRecords() {
    return [];
  }
}

(globalThis as any).IntersectionObserver = IntersectionObserverMock;

vi.stubGlobal('IntersectionObserver', IntersectionObserverMock);
