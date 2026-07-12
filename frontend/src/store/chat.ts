import { create } from 'zustand';
import { chatApi, streamChat } from '../api';
import type { ChatSession, Message, MessageWithRefs, Reference } from '../types';

interface ChatState {
  sessions: ChatSession[];
  messages: Record<number, MessageWithRefs[]>;
  currentSessionId: number | null;
  streaming: boolean;
  loading: boolean;
  warnings: string[];
  _stopFlag: boolean;
  _abortController: AbortController | null;
  fetchSessions: () => Promise<void>;
  createSession: (kbId?: number, title?: string) => Promise<ChatSession>;
  deleteSession: (id: number) => Promise<void>;
  fetchMessages: (sessionId: number) => Promise<void>;
  sendMessage: (sessionId: number, content: string, model?: string) => Promise<void>;
  setCurrentSession: (id: number | null) => void;
  stopStreaming: () => void;
  clearWarnings: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  messages: {},
  currentSessionId: null,
  streaming: false,
  loading: false,
  warnings: [],
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

  sendMessage: async (sessionId, content, model) => {
    if (get().streaming) return;

    const userMsg: MessageWithRefs = { role: 'user', content };
    const assistantMsg: MessageWithRefs = { role: 'assistant', content: '', isStreaming: true };

    // 创建 AbortController 用于真正取消 fetch 请求
    const abortController = new AbortController();

    // 记录 assistant 消息索引，避免并发流式更新覆盖其他消息
    let assistantMsgIndex = 0;

    set((state) => {
      const existingMsgs = state.messages[sessionId] || [];
      assistantMsgIndex = existingMsgs.length + 1; // user msg at [length], assistant at [length+1]
      return {
        streaming: true,
        _stopFlag: false,
        _abortController: abortController,
        messages: {
          ...state.messages,
          [sessionId]: [...existingMsgs, userMsg, assistantMsg],
        },
      };
    });

    let accContent = '';
    let finalRefs: Reference[] = [];
    let finalMsgId: number | null = null;
    let lastUpdateTime = Date.now();
    let tokenCount = 0;

    const updateStore = (isStreaming: boolean) => {
      set((state) => {
        const msgs = [...(state.messages[sessionId] || [])];
        if (assistantMsgIndex < msgs.length) {
          msgs[assistantMsgIndex] = {
            ...msgs[assistantMsgIndex],
            id: finalMsgId ?? msgs[assistantMsgIndex].id,
            content: accContent,
            references: finalRefs.length > 0 ? finalRefs : msgs[assistantMsgIndex].references,
            isStreaming,
          };
        }
        return { messages: { ...state.messages, [sessionId]: msgs } };
      });
    };

    try {
      for await (const evt of streamChat(sessionId, content, abortController.signal, 60000, model)) {
        if (get()._stopFlag) break;

        if (evt.event === 'searching') {
          accContent = '';
          updateStore(true);
        } else if (evt.event === 'model') {
          // 模型信息事件，静默处理（前端可通过 model_name 显示当前使用的模型）
        } else if (evt.event === 'delta') {
          accContent += evt.content || '';
          tokenCount++;
          const now = Date.now();
          if (now - lastUpdateTime >= 100 || tokenCount >= 16) {
            lastUpdateTime = now;
            tokenCount = 0;
            updateStore(true);
          }
        } else if (evt.event === 'done') {
          finalRefs = evt.references || [];
          finalMsgId = evt.message_id || null;
          updateStore(false);
        } else if (evt.event === 'cancelled') {
          updateStore(false);
        } else if (evt.event === 'warn') {
          set((state) => ({
            warnings: [...state.warnings, evt.message || ''],
          }));
        } else if (evt.event === 'error') {
          accContent += `\n\n**错误:** ${evt.message}`;
          updateStore(false);
        }
      }
    } catch (e: any) {
      // 用户主动取消, 不显示错误, 保留已生成的内容
      if (e?.name === 'AbortError') {
        set((state) => {
          const msgs = [...(state.messages[sessionId] || [])];
          if (assistantMsgIndex < msgs.length) {
            msgs[assistantMsgIndex] = {
              ...msgs[assistantMsgIndex],
              isStreaming: false,
            };
          }
          return { messages: { ...state.messages, [sessionId]: msgs } };
        });
      } else {
        set((state) => {
          const msgs = [...(state.messages[sessionId] || [])];
          if (assistantMsgIndex < msgs.length) {
            msgs[assistantMsgIndex] = {
              ...msgs[assistantMsgIndex],
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
        if (assistantMsgIndex < msgs.length && msgs[assistantMsgIndex].isStreaming) {
          msgs[assistantMsgIndex] = {
            ...msgs[assistantMsgIndex],
            isStreaming: false,
          };
        }
        // 竞态保护: 如果 store 中的 _abortController 已不是本次调用创建的，
        // 说明 stopStreaming 后用户已发起新的 sendMessage，不应覆盖新流的 streaming 状态
        const isOvershadowed = state._abortController !== abortController && state._abortController !== null;
        if (isOvershadowed) {
          return { messages: { ...state.messages, [sessionId]: msgs } };
        }
        return {
          streaming: false,
          _stopFlag: false,
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

  clearWarnings: () => {
    set({ warnings: [] });
  },
}));
