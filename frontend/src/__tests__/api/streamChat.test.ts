import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Hoisted mock variables for auth store (trackable across tests)
const { mockLogout, mockRefresh } = vi.hoisted(() => ({
  mockLogout: vi.fn().mockResolvedValue(undefined),
  mockRefresh: vi.fn().mockResolvedValue(false),
}));

// Mock client and auth store
vi.mock('../../api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
  extractData: (res: any) => res.data.data,
  getApiBase: () => '/api/v1',
}));

vi.mock('../../store/auth', () => ({
  useAuthStore: {
    getState: () => ({
      token: 'test-token',
      logout: mockLogout,
      refreshAccessToken: mockRefresh,
    }),
  },
}));

import { streamChat } from '../../api/chat';

/** 创建一个 mock ReadableStream，按行推送 SSE 数据 */
function createMockStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

describe('streamChat', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('should yield SSE events from stream', async () => {
    const sseData = [
      'data: {"event":"delta","content":"Hello"}\n',
      'data: {"event":"delta","content":" world"}\n',
      'data: [DONE]\n',
    ];
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: createMockStream(sseData),
      text: () => Promise.resolve(''),
    } as any);

    const events: any[] = [];
    for await (const evt of streamChat(1, 'hi')) {
      events.push(evt);
    }

    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({ event: 'delta', content: 'Hello' });
    expect(events[1]).toEqual({ event: 'delta', content: ' world' });
  });

  it('should handle 401 by calling logout', async () => {
    mockLogout.mockClear();
    mockRefresh.mockResolvedValue(false);

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      body: null,
      text: () => Promise.resolve('Unauthorized'),
    } as any);

    await expect(async () => {
      for await (const _ of streamChat(1, 'hi')) {
        // should throw before yielding
      }
    }).rejects.toThrow();

    expect(mockLogout).toHaveBeenCalled();
  });

  it('should throw on non-ok response', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      body: null,
      text: () => Promise.resolve('Internal Server Error'),
    } as any);

    await expect(async () => {
      for await (const _ of streamChat(1, 'hi')) {
        // should throw
      }
    }).rejects.toThrow('HTTP 500');
  });

  it('should throw on empty response body', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: null,
      text: () => Promise.resolve(''),
    } as any);

    await expect(async () => {
      for await (const _ of streamChat(1, 'hi')) {
        // should throw
      }
    }).rejects.toThrow();
  });

  it('should skip non-data lines and malformed JSON', async () => {
    const sseData = [
      ': comment line\n',
      '\n',
      'data: \n',
      'data: not-json\n',
      'data: {"event":"delta","content":"valid"}\n',
      'data: [DONE]\n',
    ];
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: createMockStream(sseData),
      text: () => Promise.resolve(''),
    } as any);

    const events: any[] = [];
    for await (const evt of streamChat(1, 'hi')) {
      events.push(evt);
    }

    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ event: 'delta', content: 'valid' });
  });

  it('should send POST with correct body and headers', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: createMockStream(['data: [DONE]\n']),
      text: () => Promise.resolve(''),
    } as any);

    const events: any[] = [];
    for await (const evt of streamChat(1, 'test content', undefined, 60000, 'qwen2.5')) {
      events.push(evt);
    }

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/v1/chat/sessions/1/messages',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          Authorization: 'Bearer test-token',
        }),
        body: JSON.stringify({ content: 'test content', model: 'qwen2.5' }),
      }),
    );
  });

  it('should yield model event (store layer handles silently)', async () => {
    const sseData = [
      'data: {"event":"model","model_name":"qwen2.5"}\n',
      'data: {"event":"delta","content":"response"}\n',
      'data: [DONE]\n',
    ];
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: createMockStream(sseData),
      text: () => Promise.resolve(''),
    } as any);

    const events: any[] = [];
    for await (const evt of streamChat(1, 'hi')) {
      events.push(evt);
    }

    // streamChat yields all parsed events including model; store layer decides to ignore
    expect(events).toHaveLength(2);
    expect(events[0].event).toBe('model');
    expect(events[1].event).toBe('delta');
  });

  it('should handle done event with references and message_id', async () => {
    const sseData = [
      'data: {"event":"delta","content":"answer"}\n',
      'data: {"event":"done","references":[{"id":1,"content":"ref"}],"message_id":42}\n',
    ];
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: createMockStream(sseData),
      text: () => Promise.resolve(''),
    } as any);

    const events: any[] = [];
    for await (const evt of streamChat(1, 'hi')) {
      events.push(evt);
    }

    expect(events).toHaveLength(2);
    expect(events[1].event).toBe('done');
    expect(events[1].message_id).toBe(42);
    expect(events[1].references).toHaveLength(1);
  });

  it('should yield restart event (LLM fallback signal)', async () => {
    // P0-1: restart 事件在 LLM fallback 时由后端发送，前端 isSSEEvent 白名单必须放行
    // 事件序列: delta("partial") → restart → delta("restarted") → [DONE]
    const sseData = [
      'data: {"event":"delta","content":"partial"}\n',
      'data: {"event":"restart"}\n',
      'data: {"event":"delta","content":"restarted"}\n',
      'data: [DONE]\n',
    ];
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: createMockStream(sseData),
      text: () => Promise.resolve(''),
    } as any);

    const events: any[] = [];
    for await (const evt of streamChat(1, 'hi')) {
      events.push(evt);
    }

    // restart 事件应被 yield（isSSEEvent 白名单已包含 'restart'）
    expect(events).toHaveLength(3);
    expect(events[0]).toEqual({ event: 'delta', content: 'partial' });
    expect(events[1]).toEqual({ event: 'restart' });
    expect(events[2]).toEqual({ event: 'delta', content: 'restarted' });
  });

  it('should handle pre-aborted signal', async () => {
    const controller = new AbortController();
    controller.abort();

    // When signal is already aborted, fetch should be called and immediately abort
    const abortError = new Error('Aborted');
    abortError.name = 'AbortError';
    globalThis.fetch = vi.fn().mockRejectedValue(abortError);

    await expect(async () => {
      for await (const _ of streamChat(1, 'hi', controller.signal)) {
        // should throw
      }
    }).rejects.toThrow();
  });
});
