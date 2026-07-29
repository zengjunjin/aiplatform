import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

// antd Select 的虚拟列表依赖 ResizeObserver+实际布局高度，jsdom 下不渲染全部 option
// 全局禁用 Select 虚拟化，保证 getByRole('option') 可以找到全部选项
import * as antd from 'antd';
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(antd.Select as any).defaultProps = { ...((antd.Select as any).defaultProps || {}), virtual: false };

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
type IOCallback = (entries: any[], observer: any) => void;
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
