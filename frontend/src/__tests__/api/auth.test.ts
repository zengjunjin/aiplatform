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

import { authApi } from '../../api/auth';

describe('authApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('login', () => {
    it('should call POST /auth/login with credentials', async () => {
      const mockResponse = {
        data: {
          data: {
            access_token: 'token123',
            refresh_token: 'refresh123',
            token_type: 'Bearer',
            expires_in: 3600,
            user: { id: 1, username: 'test', email: 'test@test.com', role: 'user', is_active: true, created_at: '', updated_at: '' },
          },
        },
      };
      mockPost.mockResolvedValue(mockResponse);

      const result = await authApi.login({ username: 'test', password: 'password' });

      expect(mockPost).toHaveBeenCalledWith('/auth/login', { username: 'test', password: 'password' });
      expect(result.access_token).toBe('token123');
      expect(result.user).toBeDefined();
    });
  });

  describe('register', () => {
    it('should call POST /auth/register with user data', async () => {
      const mockResponse = {
        data: {
          data: { id: 2, username: 'newuser', email: 'new@test.com', role: 'user', is_active: true, created_at: '', updated_at: '' },
        },
      };
      mockPost.mockResolvedValue(mockResponse);

      const result = await authApi.register({ username: 'newuser', email: 'new@test.com', password: 'Password1!' });

      expect(mockPost).toHaveBeenCalledWith('/auth/register', {
        username: 'newuser',
        email: 'new@test.com',
        password: 'Password1!',
      });
      expect(result.username).toBe('newuser');
    });
  });

  describe('getMe', () => {
    it('should call GET /auth/me', async () => {
      const mockResponse = {
        data: {
          data: { id: 1, username: 'test', email: 'test@test.com', role: 'user', is_active: true, created_at: '', updated_at: '' },
        },
      };
      mockGet.mockResolvedValue(mockResponse);

      const result = await authApi.getMe();

      expect(mockGet).toHaveBeenCalledWith('/auth/me');
      expect(result.username).toBe('test');
    });
  });

  describe('logout', () => {
    it('should call POST /auth/logout', async () => {
      mockPost.mockResolvedValue({ data: {} });

      await authApi.logout();

      expect(mockPost).toHaveBeenCalledWith('/auth/logout', undefined);
    });

    it('should pass refresh_token when provided', async () => {
      mockPost.mockResolvedValue({ data: {} });

      await authApi.logout('rt-token-123');

      expect(mockPost).toHaveBeenCalledWith('/auth/logout', { refresh_token: 'rt-token-123' });
    });
  });

  describe('refreshToken', () => {
    it('should call POST /auth/refresh with refresh token', async () => {
      const mockResponse = {
        data: {
          data: { access_token: 'new-token', refresh_token: 'new-refresh', token_type: 'Bearer', expires_in: 3600 },
        },
      };
      mockPost.mockResolvedValue(mockResponse);

      const result = await authApi.refreshToken('old-refresh');

      expect(mockPost).toHaveBeenCalledWith('/auth/refresh', { refresh_token: 'old-refresh' });
      expect(result.access_token).toBe('new-token');
    });
  });

  describe('changePassword', () => {
    it('should call PUT /auth/password', async () => {
      mockPut.mockResolvedValue({ data: {} });

      await authApi.changePassword({ old_password: 'old', new_password: 'new' });

      expect(mockPut).toHaveBeenCalledWith('/auth/password', { old_password: 'old', new_password: 'new' });
    });
  });
});