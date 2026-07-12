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
}));

import { useChatStore } from '../store/chat';
import { chatApi } from '../api';

describe('chatStore', () => {
  beforeEach(() => {
    useChatStore.setState({
      sessions: [],
      messages: {},
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

      const msgs = useChatStore.getState().messages[1];
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
  });
});