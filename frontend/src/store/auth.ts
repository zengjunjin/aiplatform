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
            await authApi.logout(refreshToken);
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
        // 清理 chat store，避免上一个用户的会话/消息残留 (隐私泄漏)
        const { useChatStore } = await import('./chat');
        useChatStore.getState().reset();
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
      onRehydrateStorage: () => (state, error) => {
        // 注意：onRehydrateStorage 回调在模块加载期间同步执行
        // （localStorage 是同步的，zustand toThenable 会同步调用 .then），
        // 此时 useAuthStore 处于 TDZ（Temporal Dead Zone），直接引用会抛 ReferenceError。
        // 因此：1) 诊断信息只使用 state/error 参数；2) 对 useAuthStore 的引用延迟到 setTimeout。
        if (typeof window !== 'undefined') {
          (window as unknown as { __rehydrateDebug?: unknown }).__rehydrateDebug = {
            called: true,
            stateType: typeof state,
            stateNull: !state,
            stateKeys: state && typeof state === 'object' ? Object.keys(state) : null,
            error: error ? String(error) : null,
            argRefreshToken: state?.refreshToken ? 'present' : 'null',
            argRefreshTokenExpiresAt: state?.refreshTokenExpiresAt,
            now: Date.now(),
            argExpired: state?.refreshTokenExpiresAt
              ? Date.now() > state.refreshTokenExpiresAt
              : 'n/a',
          };
        }
        // 无论 state 参数是否有效，都延迟到下一个事件循环从 store 获取真实状态
        // （setTimeout 0 确保 useAuthStore 已完成赋值，避免 TDZ）
        setTimeout(() => {
          const current = useAuthStore.getState();
          const { token, refreshToken, refreshTokenExpiresAt } = current;
          if (typeof window !== 'undefined') {
            (window as unknown as { __rehydrateDebug?: unknown }).__rehydrateDebug = {
              ...(window as unknown as { __rehydrateDebug?: Record<string, unknown> }).__rehydrateDebug,
              storeToken: token ? 'present' : 'null',
              storeRefreshToken: refreshToken ? 'present' : 'null',
              storeRefreshTokenExpiresAt: refreshTokenExpiresAt,
              storeExpired: refreshTokenExpiresAt ? Date.now() > refreshTokenExpiresAt : 'n/a',
            };
          }
          // refreshToken 不存在或本地已过期：清空用户态（token 本就不持久化）
          if (!refreshToken || (refreshTokenExpiresAt && Date.now() > refreshTokenExpiresAt)) {
            useAuthStore.setState({
              token: null,
              refreshToken: null,
              refreshTokenExpiresAt: null,
              user: null,
            });
            return;
          }
          // 已有 access_token：保持登录态, 但异步 fetchMe 更新 user 信息 (role 可能已变化)
          if (token) {
            useAuthStore.getState().fetchMe().catch(() => {
              // fetchMe 失败 (401 等) 由拦截器处理
            });
            return;
          }
          // 无 access_token 但 refreshToken 有效：异步刷新；失败时 refreshAccessToken 内部会 logout
          void useAuthStore.getState().refreshAccessToken();
        }, 0);
      },
    }
  )
);
