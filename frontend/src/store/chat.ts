import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { chatApi, streamChat, feedbackApi } from '../api';
import { globalT } from '../i18n';
import { logger } from '../utils/logger';
import type { ChatSession, Message, MessageWithRefs, Reference, MessageFeedback } from '../types';

// 本地临时消息 ID 生成器: 使用负数避免与服务器返回的正数 ID 冲突
// 用于在服务器返回真实 ID 前标识消息 (如用户消息、流式中的助手消息)
let _localIdSeq = 0;
const nextLocalId = (): number => --_localIdSeq;

interface ChatState {
  sessions: ChatSession[];
  /** 按 sessionId → messageId 索引的消息字典, 支持单条消息级别的更新 */
  messagesById: Record<number, Record<number, MessageWithRefs>>;
  /** 按 sessionId 保存的消息 ID 有序列表, 维持渲染顺序 */
  messageOrder: Record<number, number[]>;
  /** 按 messageId 缓存的 feedback, 避免每次 MessageBubble 挂载都重新拉取 */
  feedbackByMessageId: Record<number, MessageFeedback | null>;
  /** 正在拉取 feedback 的 messageId 集合, 防止并发重复请求 */
  _fetchingFeedback: Record<number, true>;
  currentSessionId: number | null;
  streaming: boolean;
  loading: boolean;
  warnings: string[];
  /** Task 48: fetchMessages 错误上报 (替代 console.error), ChatPage 监听后 message.error 提示 */
  messagesError: unknown;
  _stopFlag: boolean;
  _abortController: AbortController | null;
  fetchSessions: (signal?: AbortSignal) => Promise<void>;
  createSession: (kbId?: number, title?: string) => Promise<ChatSession>;
  deleteSession: (id: number) => Promise<void>;
  fetchMessages: (sessionId: number) => Promise<void>;
  sendMessage: (sessionId: number, content: string, model?: string) => Promise<void>;
  setCurrentSession: (id: number | null) => void;
  stopStreaming: () => void;
  clearWarnings: () => void;
  /** 清空 messagesError, 用于 ChatPage 提示后重置 */
  clearMessagesError: () => void;
  /** 重置整个 chat store (logout 时调用, 避免下一个用户看到上一个用户的会话/消息) */
  reset: () => void;
  /** Selector helper: 按 sessionId 返回有序消息数组 (非响应式, 用于命令式读取) */
  getMessagesBySession: (sessionId: number) => MessageWithRefs[];
  /** 读取 messageId 对应的 feedback, 命中缓存直接返回; 否则触发拉取并写入缓存 */
  getFeedback: (messageId: number, signal?: AbortSignal) => MessageFeedback | null | undefined;
  /** 主动写入 feedback (用于提交反馈后更新缓存) */
  setFeedback: (messageId: number, feedback: MessageFeedback | null) => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
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

  getMessagesBySession: (sessionId) => {
    const state = get();
    const order = state.messageOrder[sessionId] || [];
    const byId = state.messagesById[sessionId] || {};
    const result: MessageWithRefs[] = [];
    for (let i = 0; i < order.length; i++) {
      const msg = byId[order[i]];
      if (msg) result.push(msg);
    }
    return result;
  },

  getFeedback: (messageId, signal) => {
    const state = get();
    if (messageId in state.feedbackByMessageId) {
      return state.feedbackByMessageId[messageId];
    }
    // 防止并发重复拉取: 同一 messageId 在拉取中直接返回 undefined, 调用方按需处理
    if (state._fetchingFeedback[messageId]) return undefined;
    // 标记为拉取中, 异步拉取完成后写入缓存
    set((s) => ({ _fetchingFeedback: { ...s._fetchingFeedback, [messageId]: true } }));
    feedbackApi.getFeedback(messageId, signal).then((fb) => {
      // Task 23 (P1-FE-09): abort 后不写入缓存, 避免不必要的 store 更新
      if (signal?.aborted) {
        set((s) => {
          const { [messageId]: _removed, ...restFetching } = s._fetchingFeedback;
          return { _fetchingFeedback: restFetching };
        });
        return;
      }
      set((s) => {
        const { [messageId]: _removed, ...restFetching } = s._fetchingFeedback;
        return {
          _fetchingFeedback: restFetching,
          feedbackByMessageId: { ...s.feedbackByMessageId, [messageId]: fb || null },
        };
      });
    }).catch(() => {
      set((s) => {
        const { [messageId]: _removed, ...restFetching } = s._fetchingFeedback;
        return { _fetchingFeedback: restFetching };
      });
    });
    return undefined;
  },

  setFeedback: (messageId, feedback) => {
    set((s) => {
      // Task 5 (P1-FE-01): 限制 feedbackByMessageId 字典大小到 200 条, 避免无限增长
      const MAX_FEEDBACK = 200;
      const entries = Object.entries(s.feedbackByMessageId);
      let feedbackByMessageId = { ...s.feedbackByMessageId, [messageId]: feedback };
      // 仅在新增条目 (非已存在) 且达到上限时淘汰最旧的一条, 避免更新已存在条目时误删
      const isNew = !(messageId in s.feedbackByMessageId);
      if (isNew && entries.length >= MAX_FEEDBACK) {
        // entries 形如 [[key, value], ...], 取最旧条目的 key (字符串) 用于淘汰
        const [[oldKey]] = entries;
        const numericKey = Number(oldKey);
        const { [numericKey]: _r, ...rest } = feedbackByMessageId;
        feedbackByMessageId = rest;
      }
      return { feedbackByMessageId };
    });
  },

  fetchSessions: async (signal?: AbortSignal) => {
    set({ loading: true });
    try {
      const data = await chatApi.listSessions(1, 20, signal);
      set({ sessions: data.items || [] });
    } catch (e: unknown) {
      // 组件卸载 abort 后的 CanceledError 静默处理，不抛错
      if (e instanceof Error && e.name === 'CanceledError') {
        return;
      }
      throw e;
    } finally {
      set({ loading: false });
    }
  },

  createSession: async (kbId, title) => {
    const session = await chatApi.createSession({
      kb_id: kbId,
      title: title || globalT('chat.newSession'),
    });
    set((state) => ({ sessions: [session, ...state.sessions] }));
    return session;
  },

  deleteSession: async (id) => {
    await chatApi.deleteSession(id);
    set((state) => {
      // 清理对应会话的消息索引, 避免内存泄漏
      const { [id]: _removedMsgs, ...restMessagesById } = state.messagesById;
      const { [id]: _removedOrder, ...restMessageOrder } = state.messageOrder;
      // Task 5 (P1-FE-01): 同步清理该 session 消息对应的 feedback 缓存, 避免字典残留
      const removedMsgIds = new Set(Object.keys(state.messagesById[id] || {}).map(Number));
      const restFeedback = Object.fromEntries(
        Object.entries(state.feedbackByMessageId).filter(([k]) => !removedMsgIds.has(Number(k)))
      );
      return {
        sessions: state.sessions.filter((s) => s.id !== id),
        messagesById: restMessagesById,
        messageOrder: restMessageOrder,
        feedbackByMessageId: restFeedback,
      };
    });
  },

  fetchMessages: async (sessionId) => {
    try {
      const { messages: msgs } = await chatApi.getSession(sessionId);
      const converted: MessageWithRefs[] = (msgs || []).map((m: Message) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        created_at: m.created_at,
        references: m.references || [],
        isStreaming: false,
        // Task 39: 保留 token/latency 字段供 MessageBubble 显示 chip
        token_input: m.token_input ?? undefined,
        token_output: m.token_output ?? undefined,
        latency_ms: m.latency_ms ?? undefined,
      }));
      // 批量写入 messagesById 和 messageOrder, 避免逐条更新触发多次渲染
      const byId: Record<number, MessageWithRefs> = {};
      const order: number[] = [];
      for (const m of converted) {
        const key = m.id ?? nextLocalId();
        byId[key] = { ...m, id: key };
        order.push(key);
      }
      // Task 5 (P1-FE-01): LRU 策略限制 messagesById 字典大小, 避免无限增长
      const MAX_SESSIONS = 20;
      set((state) => {
        const allSessionIds = Object.keys(state.messagesById).map(Number);
        let messagesById = { ...state.messagesById, [sessionId]: byId };
        let messageOrder = { ...state.messageOrder, [sessionId]: order };
        // 仅在新增 session (非已存在) 且达到上限时淘汰最旧的一个, 避免重复拉取时误删
        const isNewSession = !allSessionIds.includes(sessionId);
        if (isNewSession && allSessionIds.length >= MAX_SESSIONS) {
          const toRemove = allSessionIds.find((id) => id !== sessionId);
          if (toRemove !== undefined) {
            const { [toRemove]: _r1, ...rest1 } = messagesById;
            const { [toRemove]: _r2, ...rest2 } = messageOrder;
            messagesById = rest1;
            messageOrder = rest2;
          }
        }
        return { messagesById, messageOrder };
      });
    } catch (e: unknown) {
      // Task 48: 替代 console.error, 通过 state 上报错误, 由 ChatPage 监听并 message.error 提示
      set({ messagesError: e });
    }
  },

  sendMessage: async (sessionId, content, model) => {
    if (get().streaming) return;

    // 生成本地 ID (负数), 在服务器返回真实 ID 前用于索引
    const userLocalId = nextLocalId();
    const assistantLocalId = nextLocalId();

    const userMsg: MessageWithRefs = { id: userLocalId, role: 'user', content };
    const assistantMsg: MessageWithRefs = {
      id: assistantLocalId,
      role: 'assistant',
      content: '',
      isStreaming: true,
    };

    // 创建 AbortController 用于真正取消 fetch 请求
    const abortController = new AbortController();

    set((state) => {
      const sessionById = state.messagesById[sessionId] || {};
      const sessionOrder = state.messageOrder[sessionId] || [];
      return {
        streaming: true,
        _stopFlag: false,
        _abortController: abortController,
        messagesById: {
          ...state.messagesById,
          [sessionId]: {
            ...sessionById,
            [userLocalId]: userMsg,
            [assistantLocalId]: assistantMsg,
          },
        },
        messageOrder: {
          ...state.messageOrder,
          [sessionId]: [...sessionOrder, userLocalId, assistantLocalId],
        },
      };
    });

    let accContent = '';
    let finalRefs: Reference[] = [];
    let finalMsgId: number | null = null;
    let lastUpdateTime = Date.now();
    let tokenCount = 0;

    // 流式更新: 只更新对应 messageId 的对象, 不替换整个数组
    // 其他消息对象保持引用不变, 配合 React.memo 实现最小化重渲染
    const updateAssistant = (isStreaming: boolean) => {
      set((state) => {
        const sessionById = state.messagesById[sessionId];
        if (!sessionById) return state;
        const existing = sessionById[assistantLocalId];
        if (!existing) return state;
        const updated: MessageWithRefs = {
          ...existing,
          id: finalMsgId ?? existing.id,
          content: accContent,
          isStreaming,
        };
        // 仅在 finalRefs 非空时才更新 references 字段, 避免无谓的字段赋值
        // (existing.references 通过 spread 已继承, 引用保持不变)
        if (finalRefs.length > 0) {
          updated.references = finalRefs;
        }
        return {
          messagesById: {
            ...state.messagesById,
            [sessionId]: {
              ...sessionById,
              [assistantLocalId]: updated,
            },
          },
        };
      });
    };

    try {
      for await (const evt of streamChat(sessionId, content, abortController.signal, undefined, model)) {
        if (get()._stopFlag) break;

        if (evt.event === 'searching') {
          accContent = '';
          updateAssistant(true);
        } else if (evt.event === 'restart') {
          // LLM fallback 时后端发 restart 事件，清空已显示的 primary 部分输出
          accContent = '';
          updateAssistant(true);
        } else if (evt.event === 'model') {
          // 模型信息事件，静默处理（前端可通过 model_name 显示当前使用的模型）
        } else if (evt.event === 'delta') {
          accContent += evt.content || '';
          tokenCount++;
          const now = Date.now();
          if (now - lastUpdateTime >= 100 || tokenCount >= 16) {
            lastUpdateTime = now;
            tokenCount = 0;
            updateAssistant(true);
          }
        } else if (evt.event === 'done') {
          finalRefs = evt.references || [];
          finalMsgId = evt.message_id || null;
          updateAssistant(false);
        } else if (evt.event === 'cancelled') {
          updateAssistant(false);
        } else if (evt.event === 'warn') {
          set((state) => ({
            warnings: [...state.warnings, evt.message || ''],
          }));
        } else if (evt.event === 'error') {
          accContent += `\n\n**${globalT('chat.errorLabel')}:** ${evt.message}`;
          updateAssistant(false);
        }
      }
    } catch (e: unknown) {
      // 用户主动取消, 不显示错误, 保留已生成的内容
      if (e instanceof Error && e.name === 'AbortError') {
        set((state) => {
          const sessionById = state.messagesById[sessionId];
          if (!sessionById) return state;
          const existing = sessionById[assistantLocalId];
          if (!existing) return state;
          return {
            messagesById: {
              ...state.messagesById,
              [sessionId]: {
                ...sessionById,
                [assistantLocalId]: { ...existing, isStreaming: false },
              },
            },
          };
        });
      } else {
        const errMsg = e instanceof Error ? e.message : '';
        set((state) => {
          const sessionById = state.messagesById[sessionId];
          if (!sessionById) return state;
          const existing = sessionById[assistantLocalId];
          if (!existing) return state;
          return {
            messagesById: {
              ...state.messagesById,
              [sessionId]: {
                ...sessionById,
                [assistantLocalId]: {
                  ...existing,
                  content: accContent + `\n\n❌ ${errMsg || globalT('chat.connectionLost')}`,
                  isStreaming: false,
                },
              },
            },
          };
        });
      }
    } finally {
      set((state) => {
        const sessionById = state.messagesById[sessionId];
        // 竞态保护: 如果 store 中的 _abortController 已不是本次调用创建的，
        // 说明 stopStreaming 后用户已发起新的 sendMessage，不应覆盖新流的 streaming 状态
        const isOvershadowed = state._abortController !== abortController && state._abortController !== null;
        if (!sessionById) {
          return isOvershadowed ? state : {
            streaming: false,
            _stopFlag: false,
            _abortController: null,
          };
        }
        const existing = sessionById[assistantLocalId];
        let newMessagesById = state.messagesById;
        if (existing && existing.isStreaming) {
          newMessagesById = {
            ...state.messagesById,
            [sessionId]: {
              ...sessionById,
              [assistantLocalId]: { ...existing, isStreaming: false },
            },
          };
        }
        if (isOvershadowed) {
          return { messagesById: newMessagesById };
        }
        return {
          streaming: false,
          _stopFlag: false,
          _abortController: null,
          messagesById: newMessagesById,
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

  clearMessagesError: () => {
    set({ messagesError: null });
  },

  reset: () => {
    set({
      sessions: [],
      messagesById: {},
      messageOrder: {},
      feedbackByMessageId: {},
      _fetchingFeedback: {},
      currentSessionId: null,
      warnings: [],
      messagesError: null,
    });
  },
    }),
    {
      name: 'chat-sessions-cache',
      // 持久化 sessions + 最近 5 个会话的消息（每会话最多 20 条），提升刷新体验
      partialize: (state) => ({
        sessions: state.sessions,
        messagesById: Object.fromEntries(
          Object.entries(state.messagesById)
            .slice(-5)
            .map(([k, v]) => [k, Object.fromEntries(
              Object.entries(v).slice(-20)
            )])
        ),
        messageOrder: Object.fromEntries(
          Object.entries(state.messageOrder).slice(-5)
        ),
      }),
    },
  ),
);

// Task 72: dev mode invariant - messagesById 和 messageOrder 双结构一致性校验
// 仅在开发环境下订阅 state 变化, 检测两个并行结构的 key 不一致 (长度不等或 id 缺失)
// 生产环境下此代码不会执行 (Vite tree-shaking 移除 import.meta.env.DEV === false 的分支)
// Task 37 (P1-FE-10): HMR 时取消订阅, 避免热更新后重复订阅导致内存泄漏与重复告警
if (import.meta.env.DEV) {
  const unsubscribe = useChatStore.subscribe((state) => {
    const sessionIds = new Set<number>([
      ...Object.keys(state.messageOrder).map(Number),
      ...Object.keys(state.messagesById).map(Number),
    ]);
    for (const sessionId of sessionIds) {
      const order = state.messageOrder[sessionId] || [];
      const byId = state.messagesById[sessionId] || {};
      const byIdKeyCount = Object.keys(byId).length;
      if (order.length !== byIdKeyCount) {
        logger.error(
          `[chat store invariant] session ${sessionId}: messageOrder.length (${order.length}) !== messagesById key count (${byIdKeyCount})`,
        );
      }
      for (const id of order) {
        if (!(id in byId)) {
          logger.error(
            `[chat store invariant] session ${sessionId}: id ${id} in messageOrder but missing from messagesById`,
          );
        }
      }
    }
  });
  // HMR dispose: 模块热替换时取消上一次的订阅, 防止订阅堆积
  if (import.meta.hot) {
    import.meta.hot.dispose(() => {
      unsubscribe();
    });
  }
}
