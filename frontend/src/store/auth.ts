import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { authApi } from '../api';
import type { User } from '../types';

interface AuthState {
  token: string | null;
  user: User | null;
  setAuth: (token: string, user: User | null) => void;
  logout: () => void;
  fetchMe: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, email: string, password: string) => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,

      setAuth: (token, user) => set({ token, user }),

      logout: () => {
        const token = useAuthStore.getState().token;
        if (token) {
          authApi.logout().catch(() => {});
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
    { name: 'rag-auth' }
  )
);
