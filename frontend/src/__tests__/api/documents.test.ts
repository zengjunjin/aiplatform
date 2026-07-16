import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock the axios client - use vi.hoisted for hoisted mock compatibility
const { mockGet, mockPost, mockDelete } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockDelete: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  default: {
    get: mockGet,
    post: mockPost,
    delete: mockDelete,
  },
  extractData: (res: any) => res.data.data,
  getApiBase: () => '/api/v1',
}));

// Mock store for documentApi
vi.mock('../../store/auth', () => ({
  useAuthStore: {
    getState: () => ({ token: 'test-token' }),
  },
}));

import { documentApi } from '../../api/documents';

describe('documentApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('list', () => {
    it('should call GET /documents with kb_id', async () => {
      const mockResponse = {
        data: { data: { items: [], total: 0, page: 1, page_size: 20 } },
      };
      mockGet.mockResolvedValue(mockResponse);

      const result = await documentApi.list(1, 1, 20);

      expect(mockGet).toHaveBeenCalledWith('/documents', {
        params: { kb_id: 1, page: 1, page_size: 20 },
      });
      expect(result.items).toEqual([]);
    });
  });

  describe('get', () => {
    it('should call GET /documents/:id', async () => {
      const doc = { id: 1, kb_id: 1, uploader_id: 1, filename: 'test.pdf', file_path: '', file_type: 'pdf', file_size: 1024, file_hash: '', status: 'done' as const, chunk_count: 10, error_message: null, created_at: '', updated_at: '' };
      const mockResponse = { data: { data: doc } };
      mockGet.mockResolvedValue(mockResponse);

      const result = await documentApi.get(1);

      expect(mockGet).toHaveBeenCalledWith('/documents/1');
      expect(result.filename).toBe('test.pdf');
    });
  });

  describe('delete', () => {
    it('should call DELETE /documents/:id', async () => {
      mockDelete.mockResolvedValue({ data: {} });

      await documentApi.delete(1);

      expect(mockDelete).toHaveBeenCalledWith('/documents/1');
    });
  });

  describe('reparse', () => {
    it('should call POST /documents/:id/reparse', async () => {
      const mockResponse = { data: { data: { document_id: 1, task_id: 'task-1' } } };
      mockPost.mockResolvedValue(mockResponse);

      const result = await documentApi.reparse(1);

      expect(mockPost).toHaveBeenCalledWith('/documents/1/reparse');
      expect(result.document_id).toBe(1);
    });
  });

  describe('getProgress', () => {
    it('should call GET /documents/:id/progress', async () => {
      const mockResponse = { data: { data: { status: 'done', progress: 100, chunk_count: 10, error_message: null } } };
      mockGet.mockResolvedValue(mockResponse);

      const result = await documentApi.getProgress(1);

      expect(mockGet).toHaveBeenCalledWith('/documents/1/progress');
      expect(result.status).toBe('done');
      expect(result.progress).toBe(100);
    });
  });

  describe('preview', () => {
    it('should call GET /documents/:id/preview', async () => {
      const mockResponse = {
        data: { data: { filename: 'test.pdf', file_type: 'pdf', content: 'hello', page: 1, page_size: 50, total_lines: 1, total_pages: 1 } },
      };
      mockGet.mockResolvedValue(mockResponse);

      const result = await documentApi.preview(1, 1, 50);

      expect(mockGet).toHaveBeenCalledWith('/documents/1/preview', {
        params: { page: 1, page_size: 50 },
      });
      expect(result.filename).toBe('test.pdf');
    });
  });
});