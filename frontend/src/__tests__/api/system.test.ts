import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockGet } = vi.hoisted(() => ({
  mockGet: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  default: {
    get: mockGet,
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
  extractData: (res: any) => res.data.data,
  getApiBase: () => '/api/v1',
}));

import { systemApi } from '../../api/system';

describe('systemApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('status', () => {
    it('should call GET /system/status and return system status', async () => {
      const mockStatus = {
        status: 'healthy',
        postgres: 'up',
        redis: 'up',
        ollama: 'up',
        qdrant: 'up',
        celery: 'up',
      };
      mockGet.mockResolvedValue({ data: { data: mockStatus } });

      const result = await systemApi.status();

      expect(mockGet).toHaveBeenCalledWith('/system/status');
      expect(result.status).toBe('healthy');
      expect(result.postgres).toBe('up');
    });
  });

  describe('listModels', () => {
    it('should call GET /system/models and return models list', async () => {
      const mockModels = {
        models: [
          { name: 'qwen2.5:7b', display_name: 'Qwen 2.5 7B', source: 'ollama', status: 'ready' },
          { name: 'qwen2.5:14b', display_name: 'Qwen 2.5 14B', source: 'ollama', status: 'ready' },
        ],
        default_model: 'qwen2.5:7b',
      };
      mockGet.mockResolvedValue({ data: { data: mockModels } });

      const result = await systemApi.listModels();

      expect(mockGet).toHaveBeenCalledWith('/system/models');
      expect(result.models).toHaveLength(2);
      expect(result.default_model).toBe('qwen2.5:7b');
    });

    it('should handle empty models list', async () => {
      mockGet.mockResolvedValue({ data: { data: { models: [], default_model: '' } } });

      const result = await systemApi.listModels();

      expect(result.models).toEqual([]);
    });
  });
});
