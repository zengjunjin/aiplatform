import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { authApi } from '../api';
import type { User } from '../types';

/** Refresh token 本地估算有效期：7 天（与后端一致） */
const REFRESH_TOKEN_TTL_MS = 7 * 24 * 3600 * 1000;

/**
 * 单飞锁（single-flight）：多个并发请求同时触发 401 时，只允许第一个执行 refresh，
 * 其余调用复用同一个 Promise，避免并发刷新导致 refresh_token 轮换失败。
 */
let refreshPromise: Promise<boolean> | null = null;

/** 类型守卫：检查注册响应是否包含 access_token（兼容未来自动登录） */
function hasAccessToken(data: unknown): data is { access_token: string; refresh_token?: string; user?: User } {
  return typeof data === 'object' && data !== null && 'access_token' in data && typeof (data as { access_token: unknown }).access_token === 'string';
}

interface AuthState {
  /** access_token：仅内存，不持久化，避免 XSS 窃取 */
  token: string | null;
  /** refresh_token：持久化，用于轮换 access_token */
  refreshToken: string | null;
  /** refresh_token 过期时间戳（ms）：持久化 */
  refreshTokenExpiresAt: number | null;
  user: User | null;
  themeMode: 'light' | 'dark';
  setAuth: (token: string, user: User | null) => void;
  logout: () => Promise<void>;
  toggleTheme: () => void;
  fetchMe: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, email: string, password: string) => Promise<void>;
  /** 使用 refreshToken 刷新 access_token；失败会触发 logout */
  refreshAccessToken: () => Promise<boolean>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      refreshToken: null,
      refreshTokenExpiresAt: null,
      user: null,
      themeMode: 'light' as 'light' | 'dark',

      setAuth: (token, user) => set({ token, user }),

      toggleTheme: () =>
        set((state) => ({
          themeMode: state.themeMode === 'light' ? 'dark' : 'light',
        })),

      logout: async () => {
        const { token, refreshToken } = get();
        if (token || refreshToken) {
          try {
            await authApi.logout();
          } catch {
            // 即使 blacklist 失败也继续清理本地状态
          }
        }
        set({
          token: null,
          refreshToken: null,
          refreshTokenExpiresAt: null,
          user: null,
        });
      },

      fetchMe: async () => {
        const user = await authApi.getMe();
        set({ user });
      },

      login: async (username, password) => {
        const data = await authApi.login({ username, password });
        set({
          token: data.access_token,
          refreshToken: data.refresh_token,
          refreshTokenExpiresAt: Date.now() + REFRESH_TOKEN_TTL_MS,
          user: data.user || null,
        });
      },

      register: async (username, email, password) => {
        const result = await authApi.register({ username, email, password });
        // 注册后如果接口返回了 token 就自动登录（类型守卫检查，兼容未来扩展）
        if (hasAccessToken(result)) {
          const rt = result.refresh_token;
          set({
            token: result.access_token,
            refreshToken: rt || null,
            refreshTokenExpiresAt: rt ? Date.now() + REFRESH_TOKEN_TTL_MS : null,
            user: result.user || null,
          });
        }
      },

      refreshAccessToken: async () => {
        // 单飞：如果已有 refresh 请求 pending，复用该 Promise，避免并发刷新
        if (refreshPromise) {
          return refreshPromise;
        }

        const doRefresh = async (): Promise<boolean> => {
          const { refreshToken, refreshTokenExpiresAt } = get();
          if (!refreshToken) {
            return false;
          }
          // 本地过期检查：避免无谓的网络请求
          if (refreshTokenExpiresAt && Date.now() > refreshTokenExpiresAt) {
            await get().logout();
            return false;
          }
          try {
            const data = await authApi.refreshToken(refreshToken);
            set({
              token: data.access_token,
              refreshToken: data.refresh_token,
              refreshTokenExpiresAt: Date.now() + REFRESH_TOKEN_TTL_MS,
              user: data.user || get().user,
            });
            return true;
          } catch {
            await get().logout();
            return false;
          }
        };

        refreshPromise = doRefresh().finally(() => {
          refreshPromise = null;
        });
        return refreshPromise;
      },
    }),
    {
      name: 'rag-auth',
      // 仅持久化 refreshToken / refreshTokenExpiresAt / user / themeMode
      // access_token（token）不持久化，仅内存，降低 XSS 窃取风险
      partialize: (state) => ({
        refreshToken: state.refreshToken,
        refreshTokenExpiresAt: state.refreshTokenExpiresAt,
        user: state.user,
        themeMode: state.themeMode,
      }),
      onRehydrateStorage: () => (state) => {
        if (!state) return;
        const { refreshToken, refreshTokenExpiresAt } = state;
        // refreshToken 不存在或本地已过期：清空用户态（token 本就不持久化）
        if (!refreshToken || (refreshTokenExpiresAt && Date.now() > refreshTokenExpiresAt)) {
          useAuthStore.setState({
            refreshToken: null,
            refreshTokenExpiresAt: null,
            user: null,
          });
          return;
        }
        // 未过期：异步刷新 access_token；失败时 refreshAccessToken 内部会 logout
        void useAuthStore.getState().refreshAccessToken();
      },
    }
  )
);
