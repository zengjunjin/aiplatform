import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock API before importing store (路径相对于 __tests__/store/)
vi.mock('../../api', () => ({
  chatApi: {
    listSessions: vi.fn(),
    createSession: vi.fn(),
    deleteSession: vi.fn().mockResolvedValue(undefined),
    getSession: vi.fn(),
    getMessages: vi.fn(),
  },
  streamChat: vi.fn(),
  feedbackApi: {
    getFeedback: vi.fn().mockResolvedValue(null),
    submitFeedback: vi.fn(),
  },
}));

import { useChatStore } from '../../store/chat';
import { chatApi } from '../../api';
import type { Message } from '../../types';

// 构造一条最小合法的 Message (满足 fetchMessages 中字段访问)
const makeMsg = (id: number): Message => ({
  id,
  role: 'user',
  content: `msg-${id}`,
  session_id: 0,
  references: null,
  token_input: null,
  token_output: null,
  latency_ms: null,
  created_at: '',
} as unknown as Message);

const makeFeedback = (messageId: number) => ({
  id: messageId,
  message_id: messageId,
  user_id: 1,
  rating: 1,
  comment: null,
  feedback_type: null,
  created_at: '',
});

const resetState = () =>
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

describe('chat store — Task 4 (reset) & Task 5 (字典大小限制)', () => {
  beforeEach(() => {
    resetState();
    vi.clearAllMocks();
    // clearAllMocks 不重置 mockImplementation/mockResolvedValue, 但显式重置以防万一
    vi.mocked(chatApi.deleteSession).mockResolvedValue(undefined);
  });

  describe('reset (P1-FE-02)', () => {
    it('应清空全部 chat 状态 (sessions/messages/feedback/currentSession/warnings/error)', () => {
      // 预置上一个用户的残留数据
      useChatStore.setState({
        sessions: [{ id: 1, user_id: 1, kb_id: null, title: 'S1', created_at: '', updated_at: '' }],
        messagesById: { 1: { 10: { id: 10, role: 'user', content: 'previous-user-secret' } } },
        messageOrder: { 1: [10] },
        feedbackByMessageId: { 10: makeFeedback(10) },
        _fetchingFeedback: { 10: true },
        currentSessionId: 1,
        warnings: ['old warning'],
        messagesError: new Error('prev error'),
      });

      useChatStore.getState().reset();

      const s = useChatStore.getState();
      expect(s.sessions).toEqual([]);
      expect(s.messagesById).toEqual({});
      expect(s.messageOrder).toEqual({});
      expect(s.feedbackByMessageId).toEqual({});
      expect(s._fetchingFeedback).toEqual({});
      expect(s.currentSessionId).toBeNull();
      expect(s.warnings).toEqual([]);
      expect(s.messagesError).toBeNull();
    });
  });

  describe('fetchMessages LRU 限制 20 sessions (P1-FE-01)', () => {
    it('达到 20 个 session 后拉取新 session 应淘汰最旧的', async () => {
      // 预填充 20 个 session (id 1..20)
      const messagesById: Record<number, Record<number, { id: number; role: 'user' | 'assistant'; content: string }>> = {};
      const messageOrder: Record<number, number[]> = {};
      for (let sid = 1; sid <= 20; sid++) {
        messagesById[sid] = { [sid * 100]: { id: sid * 100, role: 'user', content: `s-${sid}` } };
        messageOrder[sid] = [sid * 100];
      }
      useChatStore.setState({ messagesById, messageOrder });

      // 拉取第 21 个 (新) session
      vi.mocked(chatApi.getSession).mockResolvedValue({
        session: { id: 21, user_id: 1, kb_id: null, title: 'S21', created_at: '', updated_at: '' },
        messages: [makeMsg(2101)],
      } as any);

      await useChatStore.getState().fetchMessages(21);

      const state = useChatStore.getState();
      const sessionIds = Object.keys(state.messagesById).map(Number).sort((a, b) => a - b);
      expect(sessionIds).toHaveLength(20);
      expect(sessionIds).not.toContain(1); // 最旧的被淘汰
      expect(sessionIds).toContain(21); // 新的已写入
      // messageOrder 与 messagesById 保持一致
      expect(Object.keys(state.messageOrder)).toHaveLength(20);
      expect(state.messageOrder[21]).toEqual([2101]);
    });

    it('重复拉取已存在的 session 不应淘汰其他 session', async () => {
      // 预填充 5 个 session
      const messagesById: Record<number, Record<number, { id: number; role: 'user' | 'assistant'; content: string }>> = {};
      const messageOrder: Record<number, number[]> = {};
      for (let sid = 1; sid <= 5; sid++) {
        messagesById[sid] = { [sid]: { id: sid, role: 'user', content: `s-${sid}` } };
        messageOrder[sid] = [sid];
      }
      useChatStore.setState({ messagesById, messageOrder });

      vi.mocked(chatApi.getSession).mockResolvedValue({
        session: { id: 1, user_id: 1, kb_id: null, title: 'S1', created_at: '', updated_at: '' },
        messages: [makeMsg(1)],
      } as any);

      await useChatStore.getState().fetchMessages(1);

      const state = useChatStore.getState();
      expect(Object.keys(state.messagesById)).toHaveLength(5); // 未发生淘汰
      expect(state.messagesById[1]).toBeTruthy();
    });
  });

  describe('deleteSession 清理 feedback 缓存 (P1-FE-01)', () => {
    it('应删除被删 session 消息对应的 feedback, 保留其他 session 的 feedback', async () => {
      useChatStore.setState({
        sessions: [
          { id: 1, user_id: 1, kb_id: null, title: 'S1', created_at: '', updated_at: '' },
          { id: 2, user_id: 1, kb_id: null, title: 'S2', created_at: '', updated_at: '' },
        ],
        messagesById: {
          1: {
            10: { id: 10, role: 'user', content: 'a' },
            11: { id: 11, role: 'assistant', content: 'b' },
          },
          2: { 20: { id: 20, role: 'user', content: 'c' } },
        },
        messageOrder: { 1: [10, 11], 2: [20] },
        feedbackByMessageId: {
          10: makeFeedback(10),
          11: null,
          20: makeFeedback(20),
        },
      });

      await useChatStore.getState().deleteSession(1);

      const state = useChatStore.getState();
      expect(state.sessions).toHaveLength(1);
      expect(state.sessions[0].id).toBe(2);
      // session 1 的 feedback (msg 10, 11) 被清理
      expect(state.feedbackByMessageId[10]).toBeUndefined();
      expect(state.feedbackByMessageId[11]).toBeUndefined();
      // 其他 session 的 feedback 保留
      expect(state.feedbackByMessageId[20]).toBeTruthy();
      // messagesById / messageOrder 同步清理
      expect(state.messagesById[1]).toBeUndefined();
      expect(state.messageOrder[1]).toBeUndefined();
    });
  });

  describe('setFeedback 限制 200 条 (P1-FE-01)', () => {
    it('达到 200 条后写入新 feedback 应淘汰最旧的', () => {
      // 预填充 200 条 (id 1..200)
      const fb: Record<number, ReturnType<typeof makeFeedback>> = {};
      for (let i = 1; i <= 200; i++) {
        fb[i] = makeFeedback(i);
      }
      useChatStore.setState({ feedbackByMessageId: fb });

      // 写入第 201 条 (新)
      useChatStore.getState().setFeedback(201, makeFeedback(201));

      const state = useChatStore.getState();
      expect(Object.keys(state.feedbackByMessageId)).toHaveLength(200);
      expect(state.feedbackByMessageId[1]).toBeUndefined(); // 最旧的被淘汰
      expect(state.feedbackByMessageId[201]).toBeTruthy(); // 新的已写入
    });

    it('更新已存在的 feedback 不应淘汰其他条目', () => {
      const fb: Record<number, ReturnType<typeof makeFeedback>> = {};
      for (let i = 1; i <= 200; i++) {
        fb[i] = makeFeedback(i);
      }
      useChatStore.setState({ feedbackByMessageId: fb });

      // 更新已存在的 id=100
      const updated = { ...makeFeedback(100), comment: 'updated' };
      useChatStore.getState().setFeedback(100, updated);

      const state = useChatStore.getState();
      expect(Object.keys(state.feedbackByMessageId)).toHaveLength(200); // 未发生淘汰
      expect(state.feedbackByMessageId[1]).toBeTruthy(); // 最旧的保留
      expect((state.feedbackByMessageId[100] as { comment: string }).comment).toBe('updated');
    });
  });

  describe('消息持久化 partialize (T6/P3)', () => {
    it('partialize 应只保留最近 5 个会话, 每会话最多 20 条消息', () => {
      // 预填充 8 个 session, 每个含 25 条消息
      const messagesById: Record<number, Record<number, { id: number; role: 'user' | 'assistant'; content: string }>> = {};
      const messageOrder: Record<number, number[]> = {};
      for (let sid = 1; sid <= 8; sid++) {
        const byId: Record<number, { id: number; role: 'user' | 'assistant'; content: string }> = {};
        const order: number[] = [];
        for (let mid = 1; mid <= 25; mid++) {
          const id = sid * 100 + mid;
          byId[id] = { id, role: 'user', content: `s-${sid}-m-${mid}` };
          order.push(id);
        }
        messagesById[sid] = byId;
        messageOrder[sid] = order;
      }
      useChatStore.setState({ messagesById, messageOrder, sessions: [] });

      // 通过 persist 的 partialize 获取持久化数据
      // useChatStore.persist.getOptions() 返回 persist 配置
      const persistOptions = (useChatStore as any).persist?.getOptions?.();
      const partialized = persistOptions?.partialize?.(useChatStore.getState());

      // 验证只保留最近 5 个 session (slice(-5) 取最后 5 个 key)
      const persistedSessions = Object.keys(partialized.messagesById || {});
      expect(persistedSessions.length).toBeLessThanOrEqual(5);

      // 验证每个 session 最多 20 条消息
      for (const sid of persistedSessions) {
        const msgCount = Object.keys(partialized.messagesById[sid]).length;
        expect(msgCount).toBeLessThanOrEqual(20);
      }

      // messageOrder 也只保留 5 个
      const persistedOrders = Object.keys(partialized.messageOrder || {});
      expect(persistedOrders.length).toBeLessThanOrEqual(5);
    });

    it('partialize 应持久化 sessions 列表', () => {
      const testSessions = [
        { id: 1, user_id: 1, kb_id: null, title: 'S1', created_at: '', updated_at: '' },
      ];
      useChatStore.setState({ sessions: testSessions });

      const persistOptions = (useChatStore as any).persist?.getOptions?.();
      const partialized = persistOptions?.partialize?.(useChatStore.getState());

      expect(partialized.sessions).toEqual(testSessions);
    });
  });
});
