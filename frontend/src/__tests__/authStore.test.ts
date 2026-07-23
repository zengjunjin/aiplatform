import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock API before importing store
vi.mock('../api', () => ({
  authApi: {
    login: vi.fn(),
    register: vi.fn(),
    getMe: vi.fn(),
    logout: vi.fn().mockResolvedValue(undefined),
    refreshToken: vi.fn(),
  },
}));

import { useAuthStore } from '../store/auth';
import { authApi } from '../api';

describe('authStore', () => {
  beforeEach(() => {
    // Reset store state
    useAuthStore.setState({
      token: null,
      user: null,
      themeMode: 'light',
    });
    vi.clearAllMocks();
  });

  describe('setAuth', () => {
    it('should set token and user', () => {
      const user = { id: 1, username: 'test', email: 'test@test.com', role: 'user' as const, is_active: true, created_at: '', updated_at: '' };
      useAuthStore.getState().setAuth('test-token', user);
      const state = useAuthStore.getState();
      expect(state.token).toBe('test-token');
      expect(state.user).toEqual(user);
    });
  });

  describe('logout', () => {
    it('should clear token and user', async () => {
      const user = { id: 1, username: 'test', email: 'test@test.com', role: 'user' as const, is_active: true, created_at: '', updated_at: '' };
      useAuthStore.setState({ token: 'test-token', user });
      await useAuthStore.getState().logout();
      const state = useAuthStore.getState();
      expect(state.token).toBeNull();
      expect(state.user).toBeNull();
    });

    it('should call logout API when token exists', async () => {
      useAuthStore.setState({ token: 'test-token' });
      await useAuthStore.getState().logout();
      expect(authApi.logout).toHaveBeenCalled();
    });

    it('should not call logout API when no token', async () => {
      await useAuthStore.getState().logout();
      expect(authApi.logout).not.toHaveBeenCalled();
    });
  });

  describe('toggleTheme', () => {
    it('should toggle from light to dark', () => {
      useAuthStore.getState().toggleTheme();
      expect(useAuthStore.getState().themeMode).toBe('dark');
    });

    it('should toggle from dark to light', () => {
      useAuthStore.setState({ themeMode: 'dark' });
      useAuthStore.getState().toggleTheme();
      expect(useAuthStore.getState().themeMode).toBe('light');
    });
  });

  describe('login', () => {
    it('should set token and user on successful login', async () => {
      const mockResponse = {
        access_token: 'new-token',
        refresh_token: 'new-refresh-token',
        token_type: 'bearer',
        expires_in: 1800,
        user: { id: 1, username: 'test', email: 'test@test.com', role: 'user' as const, is_active: true, created_at: '', updated_at: '' },
      };
      vi.mocked(authApi.login).mockResolvedValue(mockResponse);

      await useAuthStore.getState().login('test', 'password');

      const state = useAuthStore.getState();
      expect(state.token).toBe('new-token');
      expect(state.user).toEqual(mockResponse.user);
    });

    it('should propagate error on login failure', async () => {
      vi.mocked(authApi.login).mockRejectedValue(new Error('Invalid credentials'));

      await expect(useAuthStore.getState().login('test', 'wrong')).rejects.toThrow('Invalid credentials');
    });
  });

  describe('register', () => {
    it('should call register API', async () => {
      const mockUser = { id: 2, username: 'newuser', email: 'new@test.com', role: 'user' as const, is_active: true, created_at: '', updated_at: '' };
      vi.mocked(authApi.register).mockResolvedValue(mockUser);

      await useAuthStore.getState().register('newuser', 'new@test.com', 'Password1!');

      expect(authApi.register).toHaveBeenCalledWith({
        username: 'newuser',
        email: 'new@test.com',
        password: 'Password1!',
      });
    });

    it('should auto-login if register returns access_token', async () => {
      const mockResponse = {
        id: 2,
        username: 'newuser',
        email: 'new@test.com',
        role: 'user' as const,
        is_active: true,
        created_at: '',
        updated_at: '',
        access_token: 'auto-token',
        user: { id: 2, username: 'newuser', email: 'new@test.com', role: 'user' as const, is_active: true, created_at: '', updated_at: '' },
      };
      vi.mocked(authApi.register).mockResolvedValue(mockResponse as any);

      await useAuthStore.getState().register('newuser', 'new@test.com', 'Password1!');

      const state = useAuthStore.getState();
      expect(state.token).toBe('auto-token');
    });
  });

  describe('fetchMe', () => {
    it('should fetch and set current user', async () => {
      const mockUser = { id: 1, username: 'test', email: 'test@test.com', role: 'user' as const, is_active: true, created_at: '', updated_at: '' };
      vi.mocked(authApi.getMe).mockResolvedValue(mockUser);

      await useAuthStore.getState().fetchMe();

      expect(useAuthStore.getState().user).toEqual(mockUser);
    });
  });

  describe('refreshAccessToken', () => {
    it('should return false when no refreshToken', async () => {
      useAuthStore.setState({ refreshToken: null });

      const result = await useAuthStore.getState().refreshAccessToken();

      expect(result).toBe(false);
    });

    it('should logout and return false when refreshToken expired', async () => {
      useAuthStore.setState({
        refreshToken: 'old-refresh',
        refreshTokenExpiresAt: Date.now() - 1000,
      });

      const result = await useAuthStore.getState().refreshAccessToken();

      expect(result).toBe(false);
      expect(useAuthStore.getState().refreshToken).toBeNull();
    });

    it('should refresh token successfully', async () => {
      useAuthStore.setState({
        token: 'old-token',
        refreshToken: 'valid-refresh',
        refreshTokenExpiresAt: Date.now() + 86400000,
        user: { id: 1, username: 'test', email: 't@e.com', role: 'user', is_active: true, created_at: '', updated_at: '' },
      });
      vi.mocked(authApi.refreshToken).mockResolvedValue({
        access_token: 'new-token',
        refresh_token: 'new-refresh',
        token_type: 'Bearer',
        expires_in: 3600,
      });

      const result = await useAuthStore.getState().refreshAccessToken();

      expect(result).toBe(true);
      expect(useAuthStore.getState().token).toBe('new-token');
      expect(useAuthStore.getState().refreshToken).toBe('new-refresh');
    });

    it('should logout and return false on refresh failure', async () => {
      useAuthStore.setState({
        token: 'old-token',
        refreshToken: 'bad-refresh',
        refreshTokenExpiresAt: Date.now() + 86400000,
      });
      vi.mocked(authApi.refreshToken).mockRejectedValue(new Error('invalid refresh'));

      const result = await useAuthStore.getState().refreshAccessToken();

      expect(result).toBe(false);
      expect(useAuthStore.getState().token).toBeNull();
      expect(useAuthStore.getState().refreshToken).toBeNull();
    });

    it('should refresh when refreshTokenExpiresAt is null', async () => {
      useAuthStore.setState({
        token: 'old-token',
        refreshToken: 'valid-refresh',
        refreshTokenExpiresAt: null,
      });
      vi.mocked(authApi.refreshToken).mockResolvedValue({
        access_token: 'new-token',
        refresh_token: 'new-refresh',
        token_type: 'Bearer',
        expires_in: 3600,
      });

      const result = await useAuthStore.getState().refreshAccessToken();

      expect(result).toBe(true);
    });
  });

  describe('logout edge cases', () => {
    it('should clear state even when logout API fails', async () => {
      useAuthStore.setState({ token: 'test-token', refreshToken: 'test-refresh' });
      vi.mocked(authApi.logout).mockRejectedValue(new Error('network'));

      await useAuthStore.getState().logout();

      expect(useAuthStore.getState().token).toBeNull();
      expect(useAuthStore.getState().refreshToken).toBeNull();
    });

    it('should call logout API when only refreshToken exists', async () => {
      useAuthStore.setState({ token: null, refreshToken: 'test-refresh' });

      await useAuthStore.getState().logout();

      expect(authApi.logout).toHaveBeenCalled();
    });
  });

  describe('register without auto-login', () => {
    it('should not set token when register returns no access_token', async () => {
      const mockUser = { id: 3, username: 'noAutoLogin', email: 'n@e.com', role: 'user' as const, is_active: true, created_at: '', updated_at: '' };
      vi.mocked(authApi.register).mockResolvedValue(mockUser);

      await useAuthStore.getState().register('noAutoLogin', 'n@e.com', 'Password1!');

      expect(useAuthStore.getState().token).toBeNull();
    });

    it('should set token but not refreshToken when register returns access_token without refresh_token', async () => {
      vi.mocked(authApi.register).mockResolvedValue({
        id: 4,
        username: 'noRt',
        email: 'r@e.com',
        role: 'user' as const,
        is_active: true,
        created_at: '',
        updated_at: '',
        access_token: 'auto-token',
      } as any);

      await useAuthStore.getState().register('noRt', 'r@e.com', 'Password1!');

      expect(useAuthStore.getState().token).toBe('auto-token');
      expect(useAuthStore.getState().refreshToken).toBeNull();
      expect(useAuthStore.getState().refreshTokenExpiresAt).toBeNull();
    });
  });
});