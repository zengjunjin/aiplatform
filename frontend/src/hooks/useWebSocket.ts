import { useEffect, useRef, useCallback } from 'react';
import { getApiBase } from '../api/client';

/** WebSocket 通知消息类型 */
export interface WSNotification {
  type: string;
  title?: string;
  message?: string;
  data?: Record<string, unknown>;
  user_id?: string;
}

/** WebSocket 服务基础 URL，从 API_BASE 提取 host 和 port */
function getWsBase(): string {
  const apiBase = getApiBase();
  const url = new URL(apiBase.startsWith('http') ? apiBase : `http://localhost${apiBase}`);
  const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${url.host}/api/v1/ws`;
}

/**
 * WebSocket 实时通知 Hook
 *
 * @param token - JWT access token（null 时不连接）
 * @param onMessage - 收到通知时的回调
 * @param options - 可选配置
 */
export function useWebSocket(
  token: string | null,
  onMessage: (data: WSNotification) => void,
  options?: {
    /** 自动重连间隔（毫秒），默认 3000 */
    reconnectInterval?: number;
    /** 心跳间隔（毫秒），默认 30000 */
    pingInterval?: number;
  }
) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);
  const onMessageRef = useRef(onMessage);

  // 保持最新的回调引用
  onMessageRef.current = onMessage;

  const { reconnectInterval = 3000, pingInterval = 30000 } = options || {};

  const clearTimers = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (pingTimerRef.current) {
      clearInterval(pingTimerRef.current);
      pingTimerRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!token || !mountedRef.current) return;

    // 通过 WebSocket 子协议传递 token，避免暴露在 URL 和访问日志中
    const wsUrl = getWsBase();
    const ws = new WebSocket(wsUrl, [`bearer.${token}`]);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[WebSocket] Connected');
      // 启动心跳
      pingTimerRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, pingInterval);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as WSNotification;
        if (data.type === 'connected') {
          console.log('[WebSocket] Authenticated:', data.user_id);
          return;
        }
        onMessageRef.current(data);
      } catch {
        console.warn('[WebSocket] Invalid message:', event.data);
      }
    };

    ws.onclose = (event) => {
      console.log('[WebSocket] Disconnected:', event.code, event.reason);
      clearTimers();
      wsRef.current = null;

      // 非正常关闭（非 4001 认证错误）时自动重连
      if (event.code !== 4001 && mountedRef.current && token) {
        reconnectTimerRef.current = setTimeout(() => {
          if (mountedRef.current && token) {
            console.log('[WebSocket] Reconnecting...');
            connect();
          }
        }, reconnectInterval);
      }
    };

    ws.onerror = (error) => {
      console.error('[WebSocket] Error:', error);
      ws.close();
    };
  }, [token, reconnectInterval, pingInterval, clearTimers]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      clearTimers();
      if (wsRef.current) {
        wsRef.current.onclose = null; // 阻止自动重连
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect, clearTimers]);
}