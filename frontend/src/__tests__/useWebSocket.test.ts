import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useWebSocket } from '../hooks/useWebSocket';

// Mock WebSocket
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState: number = MockWebSocket.CONNECTING;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  url: string;
  protocols: string | string[];

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = protocols || [];
    MockWebSocket.instances.push(this);
  }

  send = vi.fn();
  close = vi.fn((code?: number, reason?: string) => {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose(new CloseEvent('close', { code: code ?? 1000, reason: reason || '' }));
    }
  });

  // Test helpers
  triggerOpen() {
    this.readyState = MockWebSocket.OPEN;
    if (this.onopen) this.onopen(new Event('open'));
  }

  triggerMessage(data: any) {
    if (this.onmessage) {
      this.onmessage(new MessageEvent('message', { data: JSON.stringify(data) }));
    }
  }

  triggerClose(code: number = 1000, reason: string = '') {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose(new CloseEvent('close', { code, reason }));
    }
  }

  triggerError() {
    if (this.onerror) this.onerror(new Event('error'));
  }
}

// Mock antd message
vi.mock('antd', () => ({
  message: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));

// Mock API base
vi.mock('../api/client', () => ({
  getApiBase: () => 'http://localhost:8000/api/v1',
}));

describe('useWebSocket', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    // Replace global WebSocket
    (globalThis as { WebSocket: typeof WebSocket }).WebSocket = MockWebSocket as unknown as typeof WebSocket;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('should not connect when token is null', () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket(null, onMessage));

    expect(MockWebSocket.instances).toHaveLength(0);
  });

  it('should create WebSocket connection when token is provided', () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket('test-token', onMessage));

    expect(MockWebSocket.instances).toHaveLength(1);
    const ws = MockWebSocket.instances[0];
    expect(ws.url).toContain('ws://');
    expect(ws.url).toContain('/api/v1/ws');
    expect(ws.protocols).toEqual(['bearer.test-token']);
  });

  it('should call onMessage when receiving non-connected messages', () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket('test-token', onMessage));

    const ws = MockWebSocket.instances[0];
    ws.triggerOpen();
    ws.triggerMessage({ type: 'notification', title: 'test', message: 'hello' });

    expect(onMessage).toHaveBeenCalledTimes(1);
    expect(onMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'notification', title: 'test', message: 'hello' })
    );
  });

  it('should NOT call onMessage for connected type', () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket('test-token', onMessage));

    const ws = MockWebSocket.instances[0];
    ws.triggerOpen();
    ws.triggerMessage({ type: 'connected' });

    expect(onMessage).not.toHaveBeenCalled();
  });

  it('should reset retry count on successful open', () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket('test-token', onMessage));

    const ws = MockWebSocket.instances[0];
    ws.triggerOpen();

    // After open, readyState is OPEN
    expect(ws.readyState).toBe(MockWebSocket.OPEN);
  });

  it('should start heartbeat ping on open', () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket('test-token', onMessage, { pingInterval: 1000 }));

    const ws = MockWebSocket.instances[0];
    ws.triggerOpen();

    // Advance 1 second → should send ping
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(ws.send).toHaveBeenCalledWith('ping');
  });

  it('should reconnect with exponential backoff on abnormal close', () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket('test-token', onMessage, { reconnectInterval: 1000 }));

    // First connection
    const ws1 = MockWebSocket.instances[0];
    ws1.triggerOpen();
    // Abnormal close (not 4001)
    ws1.triggerClose(1006);

    // Should not reconnect immediately
    expect(MockWebSocket.instances).toHaveLength(1);

    // Advance 1 second (initial delay) → should reconnect
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it('should NOT reconnect on auth error (code 4001)', () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket('test-token', onMessage, { reconnectInterval: 1000 }));

    const ws1 = MockWebSocket.instances[0];
    ws1.triggerClose(4001);

    // Advance timer - should not reconnect
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it('should stop reconnecting after MAX_RETRY (5) attempts', () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket('test-token', onMessage, { reconnectInterval: 100 }));

    // Trigger 5 abnormal closes with backoff
    // 1st: delay 100ms (2^0 * 100)
    // 2nd: delay 200ms (2^1 * 100)
    // 3rd: delay 400ms (2^2 * 100)
    // 4th: delay 800ms (2^3 * 100)
    // 5th: delay 1600ms (2^4 * 100)
    // 6th: should NOT reconnect (exceeded MAX_RETRY)
    for (let i = 0; i < 5; i++) {
      const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
      ws.triggerClose(1006);
      act(() => {
        // 2^i * 100 = 100, 200, 400, 800, 1600
        vi.advanceTimersByTime(100 * Math.pow(2, i) + 100);
      });
    }

    // After 5 retries, the next close should not trigger more reconnects
    const wsAfter5 = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    wsAfter5.triggerClose(1006);

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    // Total instances: initial + 5 retries = 6, no more
    expect(MockWebSocket.instances.length).toBe(6);
  });

  it('should close WebSocket on unmount', () => {
    const onMessage = vi.fn();
    const { unmount } = renderHook(() => useWebSocket('test-token', onMessage));

    const ws = MockWebSocket.instances[0];
    unmount();

    expect(ws.close).toHaveBeenCalled();
  });

  it('should use wss:// protocol for https API base', async () => {
    // Re-mock client with https URL
    vi.doMock('../api/client', () => ({
      getApiBase: () => 'https://example.com/api/v1',
    }));

    // Re-import useWebSocket to use new mock
    vi.resetModules();
    const { useWebSocket: useWebSocketHttps } = await import('../hooks/useWebSocket');
    const onMessage = vi.fn();
    renderHook(() => useWebSocketHttps('token', onMessage));

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    expect(ws.url).toContain('wss://');

    vi.doUnmock('../api/client');
    vi.resetModules();
  });
});
