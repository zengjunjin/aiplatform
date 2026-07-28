import type { ErrorInfo } from 'react';
import { logger } from './logger';

/**
 * 全局错误上报与面包屑收集工具
 *
 * 当前实现：console.error + 内存缓冲面包屑（最近 10 条），定时 flush 到 localStorage。
 * 后续可在此处接入 Sentry / 自建上报端点，无需修改调用方。
 *
 * Task 19 (P1-FE-05): 改用内存数组缓冲面包屑, 定时 flush 到 localStorage,
 * 避免每次 addBreadcrumb 都同步写 localStorage 阻塞主线程。
 */

/**
 * 从 unknown 类型的错误中提取消息字符串。
 * 用于 catch (e: unknown) 块中安全地获取错误信息。
 */
export function getErrorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  if (typeof e === 'string') return e;
  return String(e);
}

/**
 * 判断错误对象是否为 antd 表单验证错误（包含 errorFields 字段）。
 */
export function isFormValidationError(e: unknown): boolean {
  return typeof e === 'object' && e !== null && 'errorFields' in e;
}

export interface Breadcrumb {
  timestamp: number;
  type: 'route' | 'api' | 'error' | 'user';
  message: string;
  data?: unknown;
}

const BREADCRUMB_KEY = 'error_breadcrumbs';
const MAX_BREADCRUMBS = 10;
const FLUSH_INTERVAL_MS = 5000;

/**
 * 内存缓冲区: 面包屑的 source of truth。
 * addBreadcrumb 仅写入内存 (O(1) 数组操作), 不阻塞主线程。
 * 定时器 + beforeunload 将内存同步到 localStorage, 供下次页面加载时恢复。
 */
let breadcrumbBuffer: Breadcrumb[] = [];

/**
 * 模块加载时从 localStorage 恢复面包屑, 保证页面刷新后历史面包屑不丢失。
 * 读取失败 (隐私模式 / 脏数据) 时回退空数组。
 */
function loadBufferFromStorage() {
  try {
    const raw = localStorage.getItem(BREADCRUMB_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      breadcrumbBuffer = parsed.slice(-MAX_BREADCRUMBS);
    }
  } catch {
    // localStorage 不可用或脏数据: 静默回退空缓冲
  }
}

/** 将内存缓冲写入 localStorage (供下次页面加载恢复)。写入失败时静默失败。 */
function writeBufferToStorage() {
  try {
    localStorage.setItem(BREADCRUMB_KEY, JSON.stringify(breadcrumbBuffer));
  } catch {
    // localStorage 不可用 / 配额满: 静默失败, 不影响业务主流程
  }
}

/** 立即将内存缓冲 flush 到 localStorage (用于 beforeunload 和测试) */
export function flushBreadcrumbs() {
  writeBufferToStorage();
}

// 模块加载时恢复缓冲
loadBufferFromStorage();

// 定时 flush (每 5 秒), 避免每次 addBreadcrumb 都写 localStorage
if (typeof window !== 'undefined') {
  setInterval(writeBufferToStorage, FLUSH_INTERVAL_MS);
  // 页面关闭前强制 flush, 避免丢失最近 5 秒内的面包屑
  window.addEventListener('beforeunload', writeBufferToStorage);
}

/**
 * 追加一条面包屑。仅写入内存缓冲, 不阻塞主线程。
 * 定时器 (5s) 和 beforeunload 会自动 flush 到 localStorage。
 */
export function addBreadcrumb(crumb: Omit<Breadcrumb, 'timestamp'>) {
  breadcrumbBuffer.push({ ...crumb, timestamp: Date.now() });
  // 保持最多 MAX_BREADCRUMBS 条, 淘汰最旧的
  if (breadcrumbBuffer.length > MAX_BREADCRUMBS) {
    breadcrumbBuffer = breadcrumbBuffer.slice(-MAX_BREADCRUMBS);
  }
}

/** 读取当前面包屑列表 (从内存读取, 无 IO 开销) */
export function getBreadcrumbs(): Breadcrumb[] {
  return breadcrumbBuffer.slice();
}

/** 清空面包屑 (同时清空内存缓冲和 localStorage) */
export function clearBreadcrumbs() {
  breadcrumbBuffer = [];
  try {
    localStorage.removeItem(BREADCRUMB_KEY);
  } catch {
    // localStorage 不可用时静默失败
  }
}

/**
 * 上报错误：输出到 console 并写入面包屑。
 * 注意：不要在此处记录密码、token 等敏感信息。
 */
export function reportError(error: Error, errorInfo?: ErrorInfo) {
  logger.error('[ErrorBoundary]', error, errorInfo);
  addBreadcrumb({
    type: 'error',
    message: `${error.name}: ${error.message}`,
    data: { stack: error.stack, componentStack: errorInfo?.componentStack },
  });
}
