import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock dependencies before importing client
const { mockRefreshAccessToken, mockLogout, mockIsTauri, mockAddBreadcrumb, mockGlobalT } = vi.hoisted(() => ({
  mockRefreshAccessToken: vi.fn(),
  mockLogout: vi.fn(),
  mockIsTauri: vi.fn(() => false),
  mockAddBreadcrumb: vi.fn(),
  mockGlobalT: vi.fn((key: string) => key),
}));

vi.mock('../../store/auth', () => ({
  useAuthStore: {
    getState: () => ({
      token: 'test-token',
      refreshAccessToken: mockRefreshAccessToken,
      logout: mockLogout,
    }),
  },
}));

vi.mock('../../utils/tauri', () => ({
  isTauri: mockIsTauri,
}));

vi.mock('../../utils/errorReporter', () => ({
  addBreadcrumb: mockAddBreadcrumb,
}));

vi.mock('../../i18n', () => ({
  globalT: mockGlobalT,
}));

import client, { getApiBase, extractData } from '../../api/client';

describe('api/client', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsTauri.mockReturnValue(false);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('getApiBase', () => {
    it('should return relative path in browser environment', () => {
      mockIsTauri.mockReturnValue(false);
      expect(getApiBase()).toBe('/api/v1');
    });

    it('should return full URL in Tauri environment', () => {
      mockIsTauri.mockReturnValue(true);
      expect(getApiBase()).toBe('http://localhost:8000/api/v1');
    });
  });

  describe('extractData', () => {
    it('should extract data field from response', () => {
      const response = { data: { data: { id: 1 }, code: 0, message: '' } };
      expect(extractData(response)).toEqual({ id: 1 });
    });

    it('should extract data field with generic type', () => {
      const response = { data: { data: 'hello', code: 0, message: '' } };
      expect(extractData<string>(response)).toBe('hello');
    });
  });

  describe('request interceptor', () => {
    it('should add Authorization header when token exists', async () => {
      const adapter = vi.fn().mockResolvedValue({
        data: { code: 0, data: { ok: true } },
        status: 200,
        statusText: 'OK',
        headers: {},
        config: { url: '/test', method: 'get' },
      } as any);
      client.defaults.adapter = adapter as any;

      await client.get('/test');

      expect(adapter).toHaveBeenCalled();
      const config = adapter.mock.calls[0][0];
      expect(config.headers.Authorization).toBe('Bearer test-token');
    });

    it('should add breadcrumb for API call', async () => {
      const adapter = vi.fn().mockResolvedValue({
        data: { code: 0, data: {} },
        status: 200,
        statusText: 'OK',
        headers: {},
        config: { url: '/test', method: 'get' },
      } as any);
      client.defaults.adapter = adapter as any;

      await client.get('/breadcrumb-test');

      expect(mockAddBreadcrumb).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'api',
          message: expect.stringContaining('GET'),
        }),
      );
    });
  });

  describe('response interceptor - success', () => {
    it('should return response when code is 0', async () => {
      const adapter = vi.fn().mockResolvedValue({
        data: { code: 0, data: { ok: true } },
        status: 200,
        statusText: 'OK',
        headers: {},
        config: { url: '/ok', method: 'get' },
      } as any);
      client.defaults.adapter = adapter as any;

      const res = await client.get('/ok');
      expect(res.data.data).toEqual({ ok: true });
    });

    it('should return response when code is undefined', async () => {
      const adapter = vi.fn().mockResolvedValue({
        data: { data: { ok: true } },
        status: 200,
        statusText: 'OK',
        headers: {},
        config: { url: '/ok', method: 'get' },
      } as any);
      client.defaults.adapter = adapter as any;

      const res = await client.get('/ok');
      expect(res.data.data).toEqual({ ok: true });
    });

    it('should reject when code is non-zero', async () => {
      const adapter = vi.fn().mockResolvedValue({
        data: { code: 500, message: 'Server error', data: null },
        status: 200,
        statusText: 'OK',
        headers: {},
        config: { url: '/err', method: 'get' },
      } as any);
      client.defaults.adapter = adapter as any;

      await expect(client.get('/err')).rejects.toThrow('Server error');
    });
  });

  describe('response interceptor - 401 handling', () => {
    it('should reject without retry for logout request 401', async () => {
      const adapter = vi.fn().mockRejectedValue({
        response: { status: 401, data: { message: 'unauthorized' } },
        config: { url: '/auth/logout', method: 'post' },
        message: 'Request failed',
      });
      client.defaults.adapter = adapter as any;

      await expect(client.post('/auth/logout')).rejects.toBeDefined();
      expect(mockRefreshAccessToken).not.toHaveBeenCalled();
    });

    it('should reject without retry for refresh request 401', async () => {
      const adapter = vi.fn().mockRejectedValue({
        response: { status: 401, data: { message: 'unauthorized' } },
        config: { url: '/auth/refresh', method: 'post' },
        message: 'Request failed',
      });
      client.defaults.adapter = adapter as any;

      await expect(client.post('/auth/refresh')).rejects.toBeDefined();
      expect(mockRefreshAccessToken).not.toHaveBeenCalled();
    });
  });

  describe('response interceptor - error messages', () => {
    it('should use response data message when available', async () => {
      const adapter = vi.fn().mockRejectedValue({
        response: { status: 500, data: { message: 'Custom error msg' } },
        config: { url: '/test', method: 'get', _retryCount: 2 },
        message: 'Request failed',
      });
      client.defaults.adapter = adapter as any;

      await expect(client.get('/test')).rejects.toThrow('Custom error msg');
    });

    it('should use error.message when no response data message', async () => {
      const adapter = vi.fn().mockRejectedValue({
        response: { status: 500, data: {} },
        config: { url: '/test', method: 'get', _retryCount: 2 },
        message: 'Network Error',
      });
      client.defaults.adapter = adapter as any;

      await expect(client.get('/test')).rejects.toThrow('Network Error');
    });

    it('should reject when config is missing', async () => {
      const adapter = vi.fn().mockRejectedValue({
        message: 'No config error',
      });
      client.defaults.adapter = adapter as any;

      await expect(client.get('/no-config')).rejects.toBeDefined();
    });
  });

  describe('response interceptor - retry logic', () => {
    it('should not retry non-GET requests', async () => {
      const adapter = vi.fn().mockRejectedValue({
        response: { status: 500, data: { message: 'Server error' } },
        config: { url: '/post', method: 'post', _retryCount: 0 },
        message: 'Request failed',
      });
      client.defaults.adapter = adapter as any;

      await expect(client.post('/post')).rejects.toThrow('Server error');
      expect(adapter).toHaveBeenCalledTimes(1);
    });
  });
});
