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
    it('should clear token and user', () => {
      const user = { id: 1, username: 'test', email: 'test@test.com', role: 'user' as const, is_active: true, created_at: '', updated_at: '' };
      useAuthStore.setState({ token: 'test-token', user });
      useAuthStore.getState().logout();
      const state = useAuthStore.getState();
      expect(state.token).toBeNull();
      expect(state.user).toBeNull();
    });

    it('should call logout API when token exists', () => {
      useAuthStore.setState({ token: 'test-token' });
      useAuthStore.getState().logout();
      expect(authApi.logout).toHaveBeenCalled();
    });

    it('should not call logout API when no token', () => {
      useAuthStore.getState().logout();
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
});