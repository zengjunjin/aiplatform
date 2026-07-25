import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock API before importing store
vi.mock('../api', () => ({
  chatApi: {
    listSessions: vi.fn(),
    createSession: vi.fn(),
    deleteSession: vi.fn(),
    getSession: vi.fn(),
  },
  streamChat: vi.fn(),
  feedbackApi: {
    getFeedback: vi.fn().mockResolvedValue(null),
    submitFeedback: vi.fn(),
  },
}));

import { useChatStore } from '../store/chat';
import { chatApi, streamChat, feedbackApi } from '../api';

describe('chatStore', () => {
  beforeEach(() => {
    useChatStore.setState({
      sessions: [],
      messagesById: {},
      messageOrder: {},
      feedbackByMessageId: {},
      _fetchingFeedback: {},
      currentSessionId: null,
      streaming: false,
      loading: false,
      _stopFlag: false,
      _abortController: null,
    });
    vi.clearAllMocks();
  });

  describe('fetchSessions', () => {
    it('should fetch and set sessions', async () => {
      const mockSessions = [
        { id: 1, user_id: 1, kb_id: null, title: 'Session 1', created_at: '', updated_at: '' },
        { id: 2, user_id: 1, kb_id: 1, title: 'Session 2', created_at: '', updated_at: '' },
      ];
      vi.mocked(chatApi.listSessions).mockResolvedValue({ items: mockSessions, total: 2, page: 1, page_size: 20 });

      await useChatStore.getState().fetchSessions();

      const state = useChatStore.getState();
      expect(state.sessions).toEqual(mockSessions);
      expect(state.loading).toBe(false);
    });

    it('should set loading to false even on error', async () => {
      vi.mocked(chatApi.listSessions).mockRejectedValue(new Error('Network error'));

      await expect(useChatStore.getState().fetchSessions()).rejects.toThrow('Network error');
      expect(useChatStore.getState().loading).toBe(false);
    });
  });

  describe('createSession', () => {
    it('should create a new session and prepend to list', async () => {
      const newSession = { id: 3, user_id: 1, kb_id: 1, title: 'New Session', created_at: '', updated_at: '' };
      vi.mocked(chatApi.createSession).mockResolvedValue(newSession);

      const result = await useChatStore.getState().createSession(1, 'New Session');

      expect(result).toEqual(newSession);
      expect(useChatStore.getState().sessions).toEqual([newSession]);
    });
  });

  describe('deleteSession', () => {
    it('should delete a session from the list', async () => {
      useChatStore.setState({
        sessions: [
          { id: 1, user_id: 1, kb_id: null, title: 'S1', created_at: '', updated_at: '' },
          { id: 2, user_id: 1, kb_id: null, title: 'S2', created_at: '', updated_at: '' },
        ],
      });

      await useChatStore.getState().deleteSession(1);

      expect(chatApi.deleteSession).toHaveBeenCalledWith(1);
      expect(useChatStore.getState().sessions).toHaveLength(1);
      expect(useChatStore.getState().sessions[0].id).toBe(2);
    });
  });

  describe('fetchMessages', () => {
    it('should fetch and set messages for a session', async () => {
      const mockMessages = [
        { id: 1, role: 'user', content: 'Hello', session_id: 1, references: null, token_input: null, token_output: null, latency_ms: null, created_at: '' },
        { id: 2, role: 'assistant', content: 'Hi', session_id: 1, references: null, token_input: null, token_output: null, latency_ms: null, created_at: '' },
      ];
      vi.mocked(chatApi.getSession).mockResolvedValue({
        session: { id: 1, user_id: 1, kb_id: null, title: 'S1', created_at: '', updated_at: '' },
        messages: mockMessages as any,
      });

      await useChatStore.getState().fetchMessages(1);

      const msgs = useChatStore.getState().getMessagesBySession(1);
      expect(msgs).toHaveLength(2);
      expect(msgs[0].role).toBe('user');
      expect(msgs[0].content).toBe('Hello');
    });
  });

  describe('setCurrentSession', () => {
    it('should set current session id', () => {
      useChatStore.getState().setCurrentSession(5);
      expect(useChatStore.getState().currentSessionId).toBe(5);
    });
  });

  describe('stopStreaming', () => {
    it('should set stop flag and streaming to false', () => {
      const mockAbort = vi.fn();
      useChatStore.setState({ _abortController: { abort: mockAbort } as any, streaming: true });

      useChatStore.getState().stopStreaming();

      expect(mockAbort).toHaveBeenCalled();
      expect(useChatStore.getState().streaming).toBe(false);
    });

    it('should handle when _abortController is null', () => {
      useChatStore.setState({ _abortController: null, streaming: true });

      useChatStore.getState().stopStreaming();

      expect(useChatStore.getState().streaming).toBe(false);
    });
  });

  describe('clearWarnings', () => {
    it('should clear all warnings', () => {
      useChatStore.setState({ warnings: ['warn1', 'warn2'] });

      useChatStore.getState().clearWarnings();

      expect(useChatStore.getState().warnings).toEqual([]);
    });
  });

  describe('getMessagesBySession', () => {
    it('should return empty array for unknown session', () => {
      const msgs = useChatStore.getState().getMessagesBySession(999);
      expect(msgs).toEqual([]);
    });

    it('should return ordered messages for known session', () => {
      useChatStore.setState({
        messagesById: {
          1: {
            10: { id: 10, role: 'user', content: 'hello' },
            11: { id: 11, role: 'assistant', content: 'hi' },
          },
        },
        messageOrder: { 1: [10, 11] },
      });

      const msgs = useChatStore.getState().getMessagesBySession(1);
      expect(msgs).toHaveLength(2);
      expect(msgs[0].id).toBe(10);
      expect(msgs[1].id).toBe(11);
    });

    it('should skip missing messages in byId', () => {
      useChatStore.setState({
        messagesById: { 1: { 10: { id: 10, role: 'user', content: 'hi' } } },
        messageOrder: { 1: [10, 99] },
      });

      const msgs = useChatStore.getState().getMessagesBySession(1);
      expect(msgs).toHaveLength(1);
    });
  });

  describe('getFeedback', () => {
    it('should return cached feedback when available', () => {
      const fb = { id: 1, message_id: 10, user_id: 1, rating: 1, comment: null, feedback_type: null, created_at: '' };
      useChatStore.setState({ feedbackByMessageId: { 10: fb } });

      const result = useChatStore.getState().getFeedback(10);
      expect(result).toEqual(fb);
    });

    it('should return null when cached as null', () => {
      useChatStore.setState({ feedbackByMessageId: { 10: null } });

      const result = useChatStore.getState().getFeedback(10);
      expect(result).toBeNull();
    });

    it('should return undefined and trigger fetch when not cached', () => {
      vi.mocked(feedbackApi.getFeedback).mockResolvedValue(null);

      const result = useChatStore.getState().getFeedback(999);
      expect(result).toBeUndefined();
      expect(feedbackApi.getFeedback).toHaveBeenCalledWith(999);
    });

    it('should return undefined when already fetching', () => {
      useChatStore.setState({ _fetchingFeedback: { 42: true } });

      const result = useChatStore.getState().getFeedback(42);
      expect(result).toBeUndefined();
    });
  });

  describe('setFeedback', () => {
    it('should write feedback to cache', () => {
      const fb = { id: 1, message_id: 10, user_id: 1, rating: 1, comment: 'good', feedback_type: null, created_at: '' };

      useChatStore.getState().setFeedback(10, fb);

      expect(useChatStore.getState().feedbackByMessageId[10]).toEqual(fb);
    });

    it('should write null feedback to cache', () => {
      useChatStore.getState().setFeedback(20, null);

      expect(useChatStore.getState().feedbackByMessageId[20]).toBeNull();
    });
  });

  describe('sendMessage', () => {
    it('should not send when already streaming', async () => {
      useChatStore.setState({ streaming: true });


      await useChatStore.getState().sendMessage(1, 'hello');

      expect(streamChat).not.toHaveBeenCalled();
    });

    it('should create user and assistant messages on send', async () => {

      vi.mocked(streamChat).mockImplementation(async function* () {
        // no events
      });

      await useChatStore.getState().sendMessage(1, 'hello');

      const msgs = useChatStore.getState().getMessagesBySession(1);
      expect(msgs).toHaveLength(2);
      expect(msgs[0].role).toBe('user');
      expect(msgs[0].content).toBe('hello');
      expect(msgs[1].role).toBe('assistant');
      expect(useChatStore.getState().streaming).toBe(false);
    });

    it('should accumulate delta content', async () => {

      vi.mocked(streamChat).mockImplementation(async function* () {
        yield { event: 'delta', content: 'Hello' };
        yield { event: 'delta', content: ' world' };
        yield { event: 'done', references: [], message_id: 100 };
      });

      await useChatStore.getState().sendMessage(1, 'hi');

      const msgs = useChatStore.getState().getMessagesBySession(1);
      const assistantMsg = msgs.find((m: any) => m.role === 'assistant')!;
      expect(assistantMsg.content).toBe('Hello world');
      expect(assistantMsg.isStreaming).toBe(false);
    });

    it('should handle error event', async () => {

      vi.mocked(streamChat).mockImplementation(async function* () {
        yield { event: 'error', message: 'something broke' };
      });

      await useChatStore.getState().sendMessage(1, 'hi');

      const msgs = useChatStore.getState().getMessagesBySession(1);
      const assistantMsg = msgs.find((m: any) => m.role === 'assistant')!;
      expect(assistantMsg.content).toContain('something broke');
      expect(assistantMsg.isStreaming).toBe(false);
    });

    it('should handle warn event', async () => {

      vi.mocked(streamChat).mockImplementation(async function* () {
        yield { event: 'warn', message: 'degraded mode' };
      });

      await useChatStore.getState().sendMessage(1, 'hi');

      expect(useChatStore.getState().warnings).toContain('degraded mode');
    });

    it('should handle stream throw with AbortError', async () => {

      const abortErr = new Error('aborted');
      abortErr.name = 'AbortError';
      // eslint-disable-next-line require-yield -- 测试用：模拟 stream 立即抛错
      vi.mocked(streamChat).mockImplementation(async function* () {
        throw abortErr;
      });

      await useChatStore.getState().sendMessage(1, 'hi');

      const msgs = useChatStore.getState().getMessagesBySession(1);
      const assistantMsg = msgs.find((m: any) => m.role === 'assistant')!;
      expect(assistantMsg.isStreaming).toBe(false);
    });

    it('should handle stream throw with generic error', async () => {

      // eslint-disable-next-line require-yield -- 测试用：模拟 stream 立即抛错
      vi.mocked(streamChat).mockImplementation(async function* () {
        throw new Error('connection lost');
      });

      await useChatStore.getState().sendMessage(1, 'hi');

      const msgs = useChatStore.getState().getMessagesBySession(1);
      const assistantMsg = msgs.find((m: any) => m.role === 'assistant')!;
      expect(assistantMsg.content).toContain('connection lost');
      expect(assistantMsg.isStreaming).toBe(false);
    });

    it('should handle cancelled event', async () => {

      vi.mocked(streamChat).mockImplementation(async function* () {
        yield { event: 'cancelled' };
      });

      await useChatStore.getState().sendMessage(1, 'hi');

      const msgs = useChatStore.getState().getMessagesBySession(1);
      const assistantMsg = msgs.find((m: any) => m.role === 'assistant')!;
      expect(assistantMsg.isStreaming).toBe(false);
    });

    it('should handle searching event', async () => {

      vi.mocked(streamChat).mockImplementation(async function* () {
        yield { event: 'searching' };
        yield { event: 'delta', content: 'result' };
        yield { event: 'done', references: [], message_id: 200 };
      });

      await useChatStore.getState().sendMessage(1, 'hi');

      const msgs = useChatStore.getState().getMessagesBySession(1);
      const assistantMsg = msgs.find((m: any) => m.role === 'assistant')!;
      expect(assistantMsg.content).toBe('result');
    });
  });
});