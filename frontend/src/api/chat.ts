import client, { extractData, getApiBase } from './client';
import { useAuthStore } from '../store/auth';
import type { ChatSession, Message, SSEEvent, PaginatedResponse } from '../types';

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
  async listSessions(page = 1, pageSize = 20): Promise<PaginatedResponse<ChatSession>> {
    const res = await client.get('/chat/sessions', {
      params: { page, page_size: pageSize },
    });
    return extractData(res) as PaginatedResponse<ChatSession>;
  },

  /** 创建会话 */
  async createSession(params: CreateSessionParams): Promise<ChatSession> {
    const res = await client.post('/chat/sessions', params);
    return extractData(res);
  },

  /** 更新会话 */
  async updateSession(id: number, params: UpdateSessionParams): Promise<ChatSession> {
    const res = await client.put(`/chat/sessions/${id}`, params);
    return extractData(res);
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
  async getMessages(sessionId: number, page = 1, pageSize = 50): Promise<Message[]> {
    const res = await client.get(`/chat/sessions/${sessionId}/messages`, {
      params: { page, page_size: pageSize },
    });
    return extractData(res);
  },
};

/**
 * SSE 流式聊天生成器 (带超时和错误处理)
 * @param signal 可选的 AbortSignal, 用于取消请求
 * @param timeoutMs 无事件超时时间(毫秒), 默认 60 秒
 */
export async function* streamChat(
  sessionId: number,
  content: string,
  signal?: AbortSignal,
  timeoutMs = 60000,
  model?: string,
): AsyncGenerator<SSEEvent> {
  const token = useAuthStore.getState().token;

  const doStream = async function* (): AsyncGenerator<SSEEvent> {
    const abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort('timeout'), timeoutMs);

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
      const resp = await fetch(`${getApiBase()}/chat/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ content, ...(model ? { model } : {}) }),
        signal: abortController.signal,
      });

      clearTimeout(timeoutId);

      if (resp.status === 401) {
        useAuthStore.getState().logout();
        throw new Error('未授权,请重新登录');
      }
      if (!resp.ok) {
        const text = await resp.text().catch(() => '');
        throw new Error(`HTTP ${resp.status}: ${text || '请求失败'}`);
      }
      if (!resp.body) throw new Error('响应体为空');

      const reader = resp.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let ended = false;
      let lastEventTime = Date.now();

      try {
        while (!ended) {
          const readPromise = reader.read();
          // 每次迭代的 per-read timer，读取成功后必须清除，避免 timer 泄漏
          let perReadTimer: ReturnType<typeof setTimeout> | undefined;
          const timeoutPromise = new Promise<never>((_, reject) => {
            perReadTimer = setTimeout(() => {
              const err = new Error('连接超时, 请检查网络或重试');
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
          lastEventTime = Date.now();

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
              const evt = JSON.parse(dataStr) as SSEEvent;
              yield evt;
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
    } catch (e: any) {
      if (e?.name === 'AbortError' && abortController.signal.reason === 'timeout') {
        const timeoutErr = new Error('服务器响应超时, 请稍后重试');
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

export interface FeedbackOut {
  id: number;
  message_id: number;
  user_id: number;
  rating: number;
  comment: string | null;
  feedback_type: string | null;
  created_at: string;
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

export const feedbackApi = {
  /** 提交反馈 */
  async submitFeedback(messageId: number, data: FeedbackCreate): Promise<FeedbackOut> {
    const res = await client.post(`/chat/messages/${messageId}/feedback`, data);
    return extractData(res);
  },

  /** 获取某条消息的反馈 */
  async getFeedback(messageId: number): Promise<FeedbackOut | null> {
    const res = await client.get(`/chat/messages/${messageId}/feedback`);
    return extractData(res);
  },

  /** 获取反馈统计（admin） */
  async getStats(kbId?: number): Promise<FeedbackStats> {
    const res = await client.get('/chat/feedback/stats', {
      params: kbId !== undefined ? { kb_id: kbId } : {},
    });
    return extractData(res);
  },

  /** 获取反馈分析（admin） */
  async getAnalysis(kbId?: number, startDate?: string, endDate?: string): Promise<any> {
    const res = await client.get('/chat/feedback/analysis', {
      params: {
        ...(kbId !== undefined ? { kb_id: kbId } : {}),
        ...(startDate ? { start_date: startDate } : {}),
        ...(endDate ? { end_date: endDate } : {}),
      },
    });
    return extractData(res);
  },

  /** 获取低分反馈列表（admin） */
  async getLowRated(params: {
    kb_id?: number;
    start_date?: string;
    end_date?: string;
    feedback_type?: string;
    page?: number;
    page_size?: number;
  }): Promise<PaginatedResponse<FeedbackDetail>> {
    const res = await client.get('/chat/feedback/low-rated', { params });
    return extractData(res) as PaginatedResponse<FeedbackDetail>;
  },
};
