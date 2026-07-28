import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock API (同时 mock chatApi 等, 因为 logout 会动态 import chat store)
vi.mock('../../api', () => ({
  authApi: {
    login: vi.fn(),
    register: vi.fn(),
    getMe: vi.fn(),
    logout: vi.fn().mockResolvedValue(undefined),
    refreshToken: vi.fn(),
  },
  chatApi: {
    listSessions: vi.fn(),
    createSession: vi.fn(),
    deleteSession: vi.fn(),
    getSession: vi.fn(),
    getMessages: vi.fn(),
  },
  streamChat: vi.fn(),
  feedbackApi: {
    getFeedback: vi.fn().mockResolvedValue(null),
    submitFeedback: vi.fn(),
  },
}));

import { useAuthStore } from '../../store/auth';
import { useChatStore } from '../../store/chat';
import { authApi } from '../../api';
import type { User } from '../../types';

const mockUser: User = {
  id: 1,
  username: 'test',
  email: 'test@test.com',
  role: 'user',
  is_active: true,
  created_at: '',
  updated_at: '',
} as unknown as User;

const resetAuthState = () =>
  useAuthStore.setState({
    token: null,
    refreshToken: null,
    refreshTokenExpiresAt: null,
    user: null,
    themeMode: 'light',
  });

const resetChatState = () =>
  useChatStore.setState({
    sessions: [],
    messagesById: {},
    messageOrder: {},
    feedbackByMessageId: {},
    _fetchingFeedback: {},
    currentSessionId: null,
    streaming: false,
    loading: false,
    warnings: [],
    messagesError: null,
    _stopFlag: false,
    _abortController: null,
  });

describe('auth store — Task 4 (logout 清理 chat) & Task 6 (rehydrate fetchMe)', () => {
  beforeEach(() => {
    localStorage.clear();
    resetAuthState();
    resetChatState();
    vi.clearAllMocks();
    vi.mocked(authApi.logout).mockResolvedValue(undefined);
  });

  describe('logout 清理 chat store (P1-FE-02)', () => {
    it('logout 应重置 chat store, 避免上一个用户消息残留', async () => {
      // 预置上一个用户的 chat 数据
      useChatStore.setState({
        sessions: [{ id: 1, user_id: 1, kb_id: null, title: 'S1', created_at: '', updated_at: '' }],
        messagesById: { 1: { 10: { id: 10, role: 'user', content: 'previous-user-secret' } } },
        messageOrder: { 1: [10] },
        feedbackByMessageId: { 10: null },
        currentSessionId: 1,
        warnings: ['old warning'],
      });
      useAuthStore.setState({
        token: 'tok',
        refreshToken: 'rt',
        refreshTokenExpiresAt: Date.now() + 100000,
        user: mockUser,
      });

      await useAuthStore.getState().logout();

      // auth 状态已清空
      const authState = useAuthStore.getState();
      expect(authState.token).toBeNull();
      expect(authState.refreshToken).toBeNull();
      expect(authState.user).toBeNull();
      // chat store 已被 reset (无上一个用户残留)
      const chatState = useChatStore.getState();
      expect(chatState.sessions).toEqual([]);
      expect(chatState.messagesById).toEqual({});
      expect(chatState.messageOrder).toEqual({});
      expect(chatState.feedbackByMessageId).toEqual({});
      expect(chatState.currentSessionId).toBeNull();
      expect(chatState.warnings).toEqual([]);
    });

    it('logout API 失败时仍应清理 chat store', async () => {
      useChatStore.setState({
        sessions: [{ id: 2, user_id: 1, kb_id: null, title: 'S2', created_at: '', updated_at: '' }],
        currentSessionId: 2,
      });
      useAuthStore.setState({ token: 'tok', refreshToken: 'rt' });
      vi.mocked(authApi.logout).mockRejectedValue(new Error('network'));

      await useAuthStore.getState().logout();

      const chatState = useChatStore.getState();
      expect(chatState.sessions).toEqual([]);
      expect(chatState.currentSessionId).toBeNull();
    });
  });

  describe('rehydrate 调用 fetchMe 更新 user 信息 (P1-FE-03)', () => {
    it('token 已存在时 rehydrate 应调用 fetchMe (role 可能已变化)', async () => {
      // 排空模块加载阶段初始 rehydrate 的 setTimeout 残留
      await new Promise((r) => setTimeout(r, 0));

      const validExpiry = Date.now() + 86400000;
      // 一次性设置完整内存状态 (token + refreshToken + user)
      // 注意: setState 会触发 persist 的 setItem 自动写入 localStorage,
      // 若只设 token 而 refreshToken 为 null, setItem 会把 localStorage 覆盖为 null,
      // 导致 rehydrate 读到空 refreshToken 走清空分支而非 fetchMe 分支。
      useAuthStore.setState({
        token: 'existing-token',
        refreshToken: 'valid-refresh',
        refreshTokenExpiresAt: validExpiry,
        user: mockUser,
      });

      vi.mocked(authApi.getMe).mockResolvedValue({ ...mockUser, role: 'admin' } as unknown as User);
      vi.mocked(authApi.getMe).mockClear();

      await useAuthStore.persist.rehydrate();
      // onRehydrateStorage 把逻辑延迟到 setTimeout(0)
      await new Promise((r) => setTimeout(r, 20));

      expect(authApi.getMe).toHaveBeenCalled();
      // fetchMe 完成后 user 已更新为最新 role
      await new Promise((r) => setTimeout(r, 0));
      expect((useAuthStore.getState().user as { role: string }).role).toBe('admin');
    });

    it('无 token 且无 refreshToken 时 rehydrate 不应调用 fetchMe / refreshToken', async () => {
      await new Promise((r) => setTimeout(r, 0));

      localStorage.setItem(
        'rag-auth',
        JSON.stringify({
          state: { refreshToken: null, refreshTokenExpiresAt: null, user: null, themeMode: 'light' },
          version: 0,
        }),
      );
      useAuthStore.setState({ token: null });

      vi.mocked(authApi.getMe).mockClear();
      vi.mocked(authApi.refreshToken).mockClear();

      await useAuthStore.persist.rehydrate();
      await new Promise((r) => setTimeout(r, 20));

      expect(authApi.getMe).not.toHaveBeenCalled();
      expect(authApi.refreshToken).not.toHaveBeenCalled();
    });
  });
});
