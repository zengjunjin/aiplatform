import { useEffect, useRef, useCallback } from 'react';
import { message } from 'antd';
import { useTranslation } from 'react-i18next';
import { getApiBase } from '../api/client';
import { logger } from '../utils/logger';

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

// 重连参数：指数退避 3s → 6s → 12s → 24s → 30s（capped）
const MAX_RETRY = 5;
const INITIAL_DELAY = 3000; // 3s
const MAX_DELAY = 30000; // 30s

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
    /** 初始重连间隔（毫秒），默认 3000；后续按指数退避翻倍直至 MAX_DELAY */
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
  const retryCountRef = useRef(0);
  const { t } = useTranslation();
  // t 通过 ref 读取，避免加入 connect 依赖导致语言切换时 WebSocket 重连
  const tRef = useRef(t);
  tRef.current = t;

  // 保持最新的回调引用
  onMessageRef.current = onMessage;

  const { reconnectInterval = INITIAL_DELAY, pingInterval = 30000 } = options || {};

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
      // 连接成功，重置重连计数
      retryCountRef.current = 0;
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
        // 认证成功, 无需日志
        if (data.type === 'connected') {
          return;
        }
        // Task 33: 处理服务端心跳 ping 事件，回复 pong（避免 NAT 空闲超时断连）
        if ('event' in data && data.event === 'ping') {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ event: 'pong' }));
          }
          return;
        }
        onMessageRef.current(data);
      } catch {
        console.warn('[WebSocket] Invalid message:', event.data);
      }
    };

    ws.onclose = (event) => {
      clearTimers();
      wsRef.current = null;

      // 非正常关闭（非 4001 认证错误）时自动重连
      if (event.code !== 4001 && mountedRef.current && token) {
        // 指数退避：达到上限后停止重连并提示用户刷新页面
        if (retryCountRef.current >= MAX_RETRY) {
          message.warning(tRef.current('errors.websocketConnectionFailed'));
          return;
        }
        const delay = Math.min(
          reconnectInterval * Math.pow(2, retryCountRef.current),
          MAX_DELAY
        );
        reconnectTimerRef.current = setTimeout(() => {
          if (mountedRef.current && token) {
            retryCountRef.current += 1;
            connect();
          }
        }, delay);
      }
    };

    ws.onerror = (error) => {
      logger.error('[WebSocket] Error:', error);
      ws.close();
    };
  }, [token, reconnectInterval, pingInterval, clearTimers]);

  useEffect(() => {
    mountedRef.current = true;
    // 每次新的 token/挂载周期开始时重置重连计数（用户手动刷新页面也会重新挂载）
    retryCountRef.current = 0;
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
