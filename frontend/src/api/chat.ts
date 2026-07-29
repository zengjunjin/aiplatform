import client, { extractData, getApiBase } from './client';
import { getWithOptionalSignal } from './helpers';
import { useAuthStore } from '../store/auth';
import { globalT } from '../i18n';
import type { ChatSession, Message, SSEEvent, PaginatedResponse, MessageFeedback } from '../types';

// 兼容旧名称: FeedbackOut 是 MessageFeedback 的别名
// (MessageBubble.tsx 仍引用 FeedbackOut, 通过 alias 避免破坏其 import 路径)
export type { MessageFeedback as FeedbackOut };

export interface CreateSessionParams {
  kb_id?: number;
  title?: string;
}

export interface UpdateSessionParams {
  title?: string;
  kb_id?: number;
}

export const chatApi = {
  /** 获取会话列表 */
  async listSessions(page = 1, pageSize = 20, signal?: AbortSignal): Promise<PaginatedResponse<ChatSession>> {
    return getWithOptionalSignal<PaginatedResponse<ChatSession>>(
      '/chat/sessions',
      { page, page_size: pageSize },
      signal,
    );
  },

  /** 创建会话 */
  async createSession(params: CreateSessionParams): Promise<ChatSession> {
    const res = await client.post('/chat/sessions', params);
    return extractData(res);
  },

  /** 更新会话 */
  async updateSession(id: number, params: UpdateSessionParams): Promise<ChatSession> {
    const res = await client.put(`/chat/sessions/${id}`, params);
    return extractData<ChatSession>(res);
  },

  /** 删除会话 */
  async deleteSession(id: number): Promise<void> {
    await client.delete(`/chat/sessions/${id}`);
  },

  /** 获取会话详情 + 消息 */
  async getSession(sessionId: number): Promise<{ session: ChatSession; messages: Message[] }> {
    const res = await client.get(`/chat/sessions/${sessionId}`);
    return extractData(res);
  },

  /** 获取消息列表 */
  async getMessages(sessionId: number, page = 1, pageSize = 50): Promise<PaginatedResponse<Message>> {
    const res = await client.get(`/chat/sessions/${sessionId}/messages`, {
      params: { page, page_size: pageSize },
    });
    return extractData<PaginatedResponse<Message>>(res);
  },
};

/** SSE 事件类型守卫: 校验解析后的 JSON 是否为合法的 SSEEvent (严格校验 event 字段) */
function isSSEEvent(obj: unknown): obj is SSEEvent {
  if (typeof obj !== 'object' || obj === null || !('event' in obj)) {
    return false;
  }
  const evt = (obj as { event: unknown }).event;
  if (typeof evt !== 'string') return false;
  return ['searching', 'delta', 'done', 'model', 'error', 'cancelled', 'warn', 'restart'].includes(evt);
}

/**
 * SSE 流式聊天生成器 (带超时和错误处理)
 * @param signal 可选的 AbortSignal, 用于取消请求
 * @param timeoutMs 无事件超时时间(毫秒), 默认 300 秒
 *
 * 注: 60s 过短，会因 LLM/Reranker 冷启动加载（reranker 加载约 4 分钟）触发误超时。
 *     300s 覆盖冷启动 + 正常生成场景；正常情况下首 token 后会持续重置计时器。
 */
export async function* streamChat(
  sessionId: number,
  content: string,
  signal?: AbortSignal,
  timeoutMs = 300000,
  model?: string,
): AsyncGenerator<SSEEvent> {
  const token = useAuthStore.getState().token;

  const doStream = async function* (): AsyncGenerator<SSEEvent> {
    const abortController = new AbortController();
    // Task 21 (P1-FE-07): 改为 let, 401 重试时重新设置 timeout
    let timeoutId = setTimeout(() => abortController.abort('timeout'), timeoutMs);

    // 转发外部 signal 的 abort 事件，使用 once 避免监听器堆积
    const onExternalAbort = () => {
      clearTimeout(timeoutId);
      abortController.abort(signal?.reason);
    };
    if (signal) {
      if (signal.aborted) {
        abortController.abort(signal.reason);
      } else {
        signal.addEventListener('abort', onExternalAbort, { once: true });
      }
    }

    try {
      const doFetch = (accessToken: string | null) =>
        fetch(`${getApiBase()}/chat/sessions/${sessionId}/messages`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
          },
          body: JSON.stringify({ content, ...(model ? { model } : {}) }),
          signal: abortController.signal,
        });

      let resp = await doFetch(token);

      clearTimeout(timeoutId);

      if (resp.status === 401) {
        // SSE 401：尝试 refresh token 后用新 token 重试一次
        const refreshed = await useAuthStore.getState().refreshAccessToken();
        if (refreshed) {
          const newToken = useAuthStore.getState().token;
          // Task 21 (P1-FE-07): 重试时重新设置 timeout, 避免原 timeout 已被 clear 导致重试 fetch 无超时保护
          timeoutId = setTimeout(() => abortController.abort('timeout'), timeoutMs);
          resp = await doFetch(newToken);
          clearTimeout(timeoutId);
        }
        // refresh 失败或重试后仍 401：清理本地态并抛错
        if (resp.status === 401) {
          await useAuthStore.getState().logout();
          throw new Error(globalT('chat.unauthorized'));
        }
      }
      if (!resp.ok) {
        const text = await resp.text().catch(() => '');
        throw new Error(`HTTP ${resp.status}: ${text || globalT('common.requestFailed')}`);
      }
      if (!resp.body) throw new Error(globalT('chat.emptyResponse'));

      const reader = resp.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let ended = false;

      try {
        while (!ended) {
          const readPromise = reader.read();
          // 每次迭代的 per-read timer，读取成功后必须清除，避免 timer 泄漏
          let perReadTimer: ReturnType<typeof setTimeout> | undefined;
          const timeoutPromise = new Promise<never>((_, reject) => {
            perReadTimer = setTimeout(() => {
              const err = new Error(globalT('chat.readTimeout'));
              err.name = 'TimeoutError';
              reject(err);
            }, timeoutMs);
          });

          let done: boolean;
          let value: Uint8Array | undefined;
          try {
            const result = await Promise.race([readPromise, timeoutPromise]);
            done = result.done;
            value = result.value;
          } catch (e) {
            reader.cancel().catch(() => {});
            throw e;
          } finally {
            // 无论成功还是失败，都清除本次迭代的 timer
            if (perReadTimer) clearTimeout(perReadTimer);
          }

          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith('data: ')) continue;

            const dataStr = trimmed.slice(6).trim();
            if (!dataStr) continue;

            if (dataStr === '[DONE]') {
              ended = true;
              break;
            }

            try {
              const parsed: unknown = JSON.parse(dataStr);
              // 类型守卫校验: 仅 yield 合法的 SSEEvent, 异常 payload 静默忽略
              if (isSSEEvent(parsed)) {
                yield parsed;
              }
            } catch (e) {
              console.warn('SSE parse error:', dataStr);
            }
          }
        }
      } finally {
        try {
          reader.releaseLock();
        } catch {
          // already released
        }
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name === 'AbortError' && abortController.signal.reason === 'timeout') {
        const timeoutErr = new Error(globalT('chat.serverTimeout'));
        timeoutErr.name = 'TimeoutError';
        throw timeoutErr;
      }
      throw e;
    } finally {
      clearTimeout(timeoutId);
      // 清理外部 signal 监听器，防止内存泄漏
      if (signal) {
        signal.removeEventListener('abort', onExternalAbort);
      }
    }
  };

  yield* doStream();
}

export default chatApi;

// ---------- 反馈 API ----------

export interface FeedbackCreate {
  rating: number; // 1 点赞, -1 点踩
  comment?: string;
  feedback_type?: string;
}

export interface FeedbackStats {
  total_feedback: number;
  positive_rate: number;
  negative_rate: number;
  by_type: Record<string, number>;
}

export interface FeedbackDetail {
  id: number;
  message_id: number;
  rating: number;
  comment: string | null;
  feedback_type: string | null;
  created_at: string;
  question: string;
  answer: string;
  session_id: number;
  kb_id: number | null;
}

export interface FeedbackAnalysis {
  period: { start: string; end: string };
  stats: FeedbackStats;
  low_rated_count: number;
  failure_patterns: Record<string, number>;
  suggestions: string[];
  low_rated_samples: Array<{
    question: string;
    answer: string;
    feedback_type: string | null;
    comment: string | null;
  }>;
}

export const feedbackApi = {
  /** 提交反馈 */
  async submitFeedback(messageId: number, data: FeedbackCreate): Promise<MessageFeedback> {
    const res = await client.post(`/chat/messages/${messageId}/feedback`, data);
    return extractData(res);
  },

  /** 获取某条消息的反馈 */
  async getFeedback(messageId: number, signal?: AbortSignal): Promise<MessageFeedback | null> {
    const res = await client.get(`/chat/messages/${messageId}/feedback`, { signal });
    return extractData<MessageFeedback | null>(res);
  },

  /** 获取反馈统计（admin） */
  async getStats(kbId?: number, signal?: AbortSignal): Promise<FeedbackStats> {
    return getWithOptionalSignal<FeedbackStats>(
      '/chat/feedback/stats',
      kbId !== undefined ? { kb_id: kbId } : {},
      signal,
    );
  },

  /** 获取反馈分析（admin） */
  async getAnalysis(kbId?: number, startDate?: string, endDate?: string, signal?: AbortSignal): Promise<FeedbackAnalysis> {
    return getWithOptionalSignal<FeedbackAnalysis>(
      '/chat/feedback/analysis',
      {
        ...(kbId !== undefined ? { kb_id: kbId } : {}),
        ...(startDate ? { start_date: startDate } : {}),
        ...(endDate ? { end_date: endDate } : {}),
      },
      signal,
    );
  },

  /** 获取低分反馈列表（admin） */
  async getLowRated(params: {
    kb_id?: number;
    start_date?: string;
    end_date?: string;
    feedback_type?: string;
    page?: number;
    page_size?: number;
  }, signal?: AbortSignal): Promise<PaginatedResponse<FeedbackDetail>> {
    return getWithOptionalSignal<PaginatedResponse<FeedbackDetail>>(
      '/chat/feedback/low-rated',
      params,
      signal,
    );
  },
};
