import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock the axios client - use vi.hoisted for hoisted mock compatibility
const { mockGet, mockPost, mockPut, mockDelete } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPut: vi.fn(),
  mockDelete: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  default: {
    get: mockGet,
    post: mockPost,
    put: mockPut,
    delete: mockDelete,
  },
  extractData: (res: any) => res.data.data,
  getApiBase: () => '/api/v1',
}));

import { kbApi } from '../../api/kb';

describe('kbApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('list', () => {
    it('should call GET /knowledge-bases', async () => {
      const mockResponse = {
        data: { data: { items: [], total: 0, page: 1, page_size: 100 } },
      };
      mockGet.mockResolvedValue(mockResponse);

      const result = await kbApi.list(1, 100);

      expect(mockGet).toHaveBeenCalledWith('/knowledge-bases', {
        params: { page: 1, page_size: 100 },
      });
      expect(result.items).toEqual([]);
    });
  });

  describe('get', () => {
    it('should call GET /knowledge-bases/:id', async () => {
      const kb = { id: 1, name: 'KB1', description: '', owner_id: 1, doc_count: 0, chunk_count: 0, collaborators: null, created_at: '', updated_at: '' };
      const mockResponse = { data: { data: kb } };
      mockGet.mockResolvedValue(mockResponse);

      const result = await kbApi.get(1);

      expect(mockGet).toHaveBeenCalledWith('/knowledge-bases/1');
      expect(result.name).toBe('KB1');
    });
  });

  describe('create', () => {
    it('should call POST /knowledge-bases', async () => {
      const kb = { id: 1, name: 'New KB', description: 'desc', owner_id: 1, doc_count: 0, chunk_count: 0, collaborators: null, created_at: '', updated_at: '' };
      const mockResponse = { data: { data: kb } };
      mockPost.mockResolvedValue(mockResponse);

      const result = await kbApi.create({ name: 'New KB', description: 'desc' });

      expect(mockPost).toHaveBeenCalledWith('/knowledge-bases', { name: 'New KB', description: 'desc' });
      expect(result).toEqual(kb);
    });
  });

  describe('update', () => {
    it('should call PUT /knowledge-bases/:id', async () => {
      const kb = { id: 1, name: 'Updated', description: 'new', owner_id: 1, doc_count: 0, chunk_count: 0, collaborators: null, created_at: '', updated_at: '' };
      const mockResponse = { data: { data: kb } };
      mockPut.mockResolvedValue(mockResponse);

      const result = await kbApi.update(1, { name: 'Updated', description: 'new' });

      expect(mockPut).toHaveBeenCalledWith('/knowledge-bases/1', { name: 'Updated', description: 'new' });
      expect(result).toEqual(kb);
    });
  });

  describe('delete', () => {
    it('should call DELETE /knowledge-bases/:id', async () => {
      mockDelete.mockResolvedValue({ data: {} });

      await kbApi.delete(1);

      expect(mockDelete).toHaveBeenCalledWith('/knowledge-bases/1');
    });
  });

  describe('getCollaborators', () => {
    it('should call GET /knowledge-bases/:id/collaborators', async () => {
      const mockResponse = { data: { data: [] } };
      mockGet.mockResolvedValue(mockResponse);

      const result = await kbApi.getCollaborators(1);

      expect(mockGet).toHaveBeenCalledWith('/knowledge-bases/1/collaborators');
      expect(result).toEqual([]);
    });
  });

  describe('addCollaborator', () => {
    it('should call POST /knowledge-bases/:id/collaborators', async () => {
      const collab = { user_id: 2, username: 'user2', permission: 'read' };
      const mockResponse = { data: { data: collab } };
      mockPost.mockResolvedValue(mockResponse);

      const result = await kbApi.addCollaborator(1, { user_id: 2, permission: 'read' });

      expect(mockPost).toHaveBeenCalledWith('/knowledge-bases/1/collaborators', { user_id: 2, permission: 'read' });
      expect(result).toEqual(collab);
    });
  });

  describe('removeCollaborator', () => {
    it('should call DELETE /knowledge-bases/:id/collaborators/:userId', async () => {
      mockDelete.mockResolvedValue({ data: {} });

      await kbApi.removeCollaborator(1, 2);

      expect(mockDelete).toHaveBeenCalledWith('/knowledge-bases/1/collaborators/2');
    });
  });
});