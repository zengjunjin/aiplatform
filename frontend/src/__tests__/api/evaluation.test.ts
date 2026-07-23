import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockGet, mockPost, mockDelete } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockDelete: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  default: {
    get: mockGet,
    post: mockPost,
    put: vi.fn(),
    delete: mockDelete,
  },
  extractData: (res: any) => res.data.data,
  getApiBase: () => '/api/v1',
}));

import evaluationApi from '../../api/evaluation';

describe('evaluationApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('triggerEvaluation', () => {
    it('should call POST /evaluation/runs with kb_id and num_questions', async () => {
      const mockRun = { id: 1, kb_id: 1, status: 'pending', num_questions: 50, created_at: '', updated_at: '' };
      mockPost.mockResolvedValue({ data: { data: mockRun } });

      const result = await evaluationApi.triggerEvaluation(1, 50);

      expect(mockPost).toHaveBeenCalledWith('/evaluation/runs', null, {
        params: { kb_id: 1, num_questions: 50 },
      });
      expect(result).toEqual(mockRun);
    });

    it('should use default num_questions=50 when not provided', async () => {
      mockPost.mockResolvedValue({ data: { data: { id: 1 } } });

      await evaluationApi.triggerEvaluation(2);

      expect(mockPost).toHaveBeenCalledWith('/evaluation/runs', null, {
        params: { kb_id: 2, num_questions: 50 },
      });
    });
  });

  describe('listRuns', () => {
    it('should call GET /evaluation/runs with params', async () => {
      const mockData = { items: [], total: 0, page: 1, page_size: 20, total_pages: 0 };
      mockGet.mockResolvedValue({ data: { data: mockData } });

      const result = await evaluationApi.listRuns({ kb_id: 1, page: 1, page_size: 20 });

      expect(mockGet).toHaveBeenCalledWith('/evaluation/runs', {
        params: { kb_id: 1, page: 1, page_size: 20 },
      });
      expect(result.total).toBe(0);
    });

    it('should call GET /evaluation/runs without params', async () => {
      mockGet.mockResolvedValue({ data: { data: { items: [], total: 0 } } });

      await evaluationApi.listRuns();

      expect(mockGet).toHaveBeenCalledWith('/evaluation/runs', { params: undefined });
    });
  });

  describe('getRun', () => {
    it('should call GET /evaluation/runs/:id', async () => {
      const mockRun = { id: 1, kb_id: 1, status: 'completed', num_questions: 50, created_at: '', updated_at: '' };
      mockGet.mockResolvedValue({ data: { data: mockRun } });

      const result = await evaluationApi.getRun(1);

      expect(mockGet).toHaveBeenCalledWith('/evaluation/runs/1');
      expect(result.id).toBe(1);
    });
  });

  describe('getResults', () => {
    it('should call GET /evaluation/runs/:id/results with pagination', async () => {
      mockGet.mockResolvedValue({ data: { data: { items: [], total: 0, page: 1, page_size: 20, total_pages: 0 } } });

      await evaluationApi.getResults(1, 1, 20);

      expect(mockGet).toHaveBeenCalledWith('/evaluation/runs/1/results', {
        params: { page: 1, page_size: 20 },
      });
    });
  });

  describe('deleteRun', () => {
    it('should call DELETE /evaluation/runs/:id', async () => {
      mockDelete.mockResolvedValue({ data: { data: null } });

      await evaluationApi.deleteRun(1);

      expect(mockDelete).toHaveBeenCalledWith('/evaluation/runs/1');
    });
  });
});
