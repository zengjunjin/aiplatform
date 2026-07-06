import client, { extractData, API_BASE } from './client';
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
): AsyncGenerator<SSEEvent> {
  const token = useAuthStore.getState().token;

  const doStream = async function* (): AsyncGenerator<SSEEvent> {
    const abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort('timeout'), timeoutMs);

    if (signal) {
      signal.addEventListener('abort', () => {
        clearTimeout(timeoutId);
        abortController.abort(signal.reason);
      });
    }

    try {
      const resp = await fetch(`${API_BASE}/chat/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ content }),
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
          const timeoutPromise = new Promise<never>((_, reject) => {
            const id = setTimeout(() => {
              clearTimeout(id);
              const err = new Error('连接超时, 请检查网络或重试');
              err.name = 'TimeoutError';
              reject(err);
            }, timeoutMs);
          });

          const { done, value } = await Promise.race([readPromise, timeoutPromise]).catch((e) => {
            reader.cancel().catch(() => {});
            throw e;
          });

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
    }
  };

  yield* doStream();
}

export default chatApi;
