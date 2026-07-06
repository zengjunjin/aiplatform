import { create } from 'zustand';
import { chatApi, streamChat } from '../api';
import type { ChatSession, Message, MessageWithRefs, Reference } from '../types';

interface ChatState {
  sessions: ChatSession[];
  messages: Record<number, MessageWithRefs[]>;
  currentSessionId: number | null;
  streaming: boolean;
  loading: boolean;
  _stopFlag: boolean;
  _abortController: AbortController | null;
  fetchSessions: () => Promise<void>;
  createSession: (kbId?: number, title?: string) => Promise<ChatSession>;
  deleteSession: (id: number) => Promise<void>;
  fetchMessages: (sessionId: number) => Promise<void>;
  sendMessage: (sessionId: number, content: string) => Promise<void>;
  setCurrentSession: (id: number | null) => void;
  stopStreaming: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  messages: {},
  currentSessionId: null,
  streaming: false,
  loading: false,
  _stopFlag: false,
  _abortController: null,

  fetchSessions: async () => {
    set({ loading: true });
    try {
      const data = await chatApi.listSessions();
      set({ sessions: data.items || [] });
    } finally {
      set({ loading: false });
    }
  },

  createSession: async (kbId, title) => {
    const session = await chatApi.createSession({
      kb_id: kbId,
      title: title || '新对话',
    });
    set((state) => ({ sessions: [session, ...state.sessions] }));
    return session;
  },

  deleteSession: async (id) => {
    await chatApi.deleteSession(id);
    set((state) => ({
      sessions: state.sessions.filter((s) => s.id !== id),
    }));
  },

  fetchMessages: async (sessionId) => {
    try {
      const { messages: msgs } = await chatApi.getSession(sessionId);
      const converted: MessageWithRefs[] = (msgs || []).map((m: any) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        created_at: m.created_at,
        references: m.references || [],
        isStreaming: false,
      }));
      set((state) => ({
        messages: { ...state.messages, [sessionId]: converted },
      }));
    } catch (e: any) {
      console.error('fetch messages error:', e);
    }
  },

  sendMessage: async (sessionId, content) => {
    if (get().streaming) return;

    const userMsg: MessageWithRefs = { role: 'user', content };
    const assistantMsg: MessageWithRefs = { role: 'assistant', content: '', isStreaming: true };

    // 创建 AbortController 用于真正取消 fetch 请求
    const abortController = new AbortController();

    set((state) => ({
      streaming: true,
      _stopFlag: false,
      _abortController: abortController,
      messages: {
        ...state.messages,
        [sessionId]: [...(state.messages[sessionId] || []), userMsg, assistantMsg],
      },
    }));

    let accContent = '';
    let finalRefs: Reference[] = [];
    let finalMsgId: number | null = null;

    try {
      for await (const evt of streamChat(sessionId, content, abortController.signal)) {
        if (get()._stopFlag) break;

        if (evt.event === 'searching') {
          accContent = '';
        } else if (evt.event === 'delta') {
          accContent += evt.content || '';
        } else if (evt.event === 'done') {
          finalRefs = evt.references || [];
          finalMsgId = evt.message_id || null;
        } else if (evt.event === 'error') {
          accContent += `\n\n**错误:** ${evt.message}`;
        }

        set((state) => {
          const msgs = [...(state.messages[sessionId] || [])];
          if (msgs.length > 0) {
            msgs[msgs.length - 1] = {
              ...msgs[msgs.length - 1],
              id: finalMsgId ?? msgs[msgs.length - 1].id,
              content: accContent,
              references: finalRefs.length > 0 ? finalRefs : msgs[msgs.length - 1].references,
              isStreaming: evt.event !== 'done' && evt.event !== 'error',
            };
          }
          return { messages: { ...state.messages, [sessionId]: msgs } };
        });
      }
    } catch (e: any) {
      // 用户主动取消, 不显示错误, 保留已生成的内容
      if (e?.name === 'AbortError') {
        set((state) => {
          const msgs = [...(state.messages[sessionId] || [])];
          if (msgs.length > 0) {
            msgs[msgs.length - 1] = {
              ...msgs[msgs.length - 1],
              isStreaming: false,
            };
          }
          return { messages: { ...state.messages, [sessionId]: msgs } };
        });
      } else {
        set((state) => {
          const msgs = [...(state.messages[sessionId] || [])];
          if (msgs.length > 0) {
            msgs[msgs.length - 1] = {
              ...msgs[msgs.length - 1],
              content: accContent + `\n\n❌ ${e.message || '连接中断,请重试'}`,
              isStreaming: false,
            };
          }
          return { messages: { ...state.messages, [sessionId]: msgs } };
        });
      }
    } finally {
      set((state) => {
        const msgs = [...(state.messages[sessionId] || [])];
        if (msgs.length > 0 && msgs[msgs.length - 1].isStreaming) {
          msgs[msgs.length - 1] = {
            ...msgs[msgs.length - 1],
            isStreaming: false,
          };
        }
        return {
          streaming: false,
          _abortController: null,
          messages: { ...state.messages, [sessionId]: msgs },
        };
      });
    }
  },

  setCurrentSession: (id) => {
    set({ currentSessionId: id });
  },

  stopStreaming: () => {
    const { _abortController } = get();
    if (_abortController) {
      _abortController.abort();
    }
    set({ _stopFlag: true, streaming: false, _abortController: null });
  },
}));
