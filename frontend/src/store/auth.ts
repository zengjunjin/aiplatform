import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { authApi } from '../api';
import type { User } from '../types';

interface AuthState {
  token: string | null;
  user: User | null;
  themeMode: 'light' | 'dark';
  setAuth: (token: string, user: User | null) => void;
  logout: () => void;
  toggleTheme: () => void;
  fetchMe: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, email: string, password: string) => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      themeMode: 'light' as 'light' | 'dark',

      setAuth: (token, user) => set({ token, user }),

      toggleTheme: () =>
        set((state) => ({
          themeMode: state.themeMode === 'light' ? 'dark' : 'light',
        })),

      logout: async () => {
        const token = useAuthStore.getState().token;
        if (token) {
          try {
            await authApi.logout();
          } catch {
            // 即使 blacklist 失败也继续清理本地状态
          }
        }
        set({ token: null, user: null });
      },

      fetchMe: async () => {
        const user = await authApi.getMe();
        set({ user });
      },

      login: async (username, password) => {
        const data = await authApi.login({ username, password });
        set({
          token: data.access_token,
          user: data.user || null,
        });
      },

      register: async (username, email, password) => {
        const user = await authApi.register({ username, email, password });
        // 注册后如果接口返回了 token 就自动登录
        if ((user as any).access_token) {
          set({
            token: (user as any).access_token,
            user: (user as any).user || user,
          });
        }
      },
    }),
    {
      name: 'rag-auth',
      // 仅持久化数据字段，不持久化方法
      partialize: (state) => ({
        token: state.token,
        user: state.user,
        themeMode: state.themeMode,
      }),
    }
  )
);
