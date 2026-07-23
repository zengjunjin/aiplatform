import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockGet, mockPut } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPut: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  default: {
    get: mockGet,
    post: vi.fn(),
    put: mockPut,
    delete: vi.fn(),
  },
  extractData: (res: any) => res.data.data,
  getApiBase: () => '/api/v1',
}));

import { usersApi } from '../../api/users';

describe('usersApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('list', () => {
    it('should call GET /users with params and return paginated data', async () => {
      const mockData = {
        items: [{ id: 1, username: 'u1', email: 'u1@e.com', role: 'user', is_active: true, created_at: '', updated_at: '' }],
        total: 1,
      };
      mockGet.mockResolvedValue({ data: { data: mockData } });

      const result = await usersApi.list({ page: 1, page_size: 20, keyword: 'u1' });

      expect(mockGet).toHaveBeenCalledWith('/users', {
        params: { page: 1, page_size: 20, keyword: 'u1' },
      });
      expect(result.items).toHaveLength(1);
      expect(result.total).toBe(1);
    });

    it('should handle array response format (legacy)', async () => {
      const arr = [
        { id: 1, username: 'a', email: 'a@e.com', role: 'user', is_active: true, created_at: '', updated_at: '' },
        { id: 2, username: 'b', email: 'b@e.com', role: 'admin', is_active: true, created_at: '', updated_at: '' },
      ];
      mockGet.mockResolvedValue({ data: { data: arr } });

      const result = await usersApi.list();

      expect(result.items).toHaveLength(2);
      expect(result.total).toBe(2);
    });

    it('should use default empty params when none provided', async () => {
      mockGet.mockResolvedValue({ data: { data: { items: [], total: 0 } } });

      await usersApi.list();

      expect(mockGet).toHaveBeenCalledWith('/users', { params: {} });
    });

    it('should return empty items when data is null', async () => {
      mockGet.mockResolvedValue({ data: { data: null } });

      const result = await usersApi.list();

      expect(result.items).toEqual([]);
      expect(result.total).toBe(0);
    });
  });

  describe('updateRole', () => {
    it('should call PUT /users/:id/role', async () => {
      mockPut.mockResolvedValue({ data: {} });

      await usersApi.updateRole(1, 'admin');

      expect(mockPut).toHaveBeenCalledWith('/users/1/role', { role: 'admin' });
    });
  });

  describe('updateStatus', () => {
    it('should call PUT /users/:id/status', async () => {
      mockPut.mockResolvedValue({ data: {} });

      await usersApi.updateStatus(1, false);

      expect(mockPut).toHaveBeenCalledWith('/users/1/status', { is_active: false });
    });

    it('should call PUT /users/:id/status with true', async () => {
      mockPut.mockResolvedValue({ data: {} });

      await usersApi.updateStatus(2, true);

      expect(mockPut).toHaveBeenCalledWith('/users/2/status', { is_active: true });
    });
  });
});
