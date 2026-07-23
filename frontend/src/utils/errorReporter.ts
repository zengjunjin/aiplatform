import type { ErrorInfo } from 'react';

/**
 * 全局错误上报与面包屑收集工具
 *
 * 当前实现：console.error + localStorage 面包屑（最近 10 条）。
 * 后续可在此处接入 Sentry / 自建上报端点，无需修改调用方。
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

/**
 * Task 38: 从 localStorage 安全读取面包屑列表
 * JSON.parse 失败或解析结果非数组时回退空数组, 避免脏数据导致后续 push 抛错
 */
function readBreadcrumbs(): Breadcrumb[] {
  try {
    const raw = localStorage.getItem(BREADCRUMB_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/**
 * 追加一条面包屑。localStorage 不可用（隐私模式 / 配额满）时静默失败，
 * 不影响业务主流程。
 */
export function addBreadcrumb(crumb: Omit<Breadcrumb, 'timestamp'>) {
  try {
    const existing = readBreadcrumbs();
    existing.push({ ...crumb, timestamp: Date.now() });
    const trimmed = existing.slice(-MAX_BREADCRUMBS);
    localStorage.setItem(BREADCRUMB_KEY, JSON.stringify(trimmed));
  } catch {
    // localStorage 不可用时静默失败
  }
}

/** 读取当前面包屑列表（无法读取时返回空数组） */
export function getBreadcrumbs(): Breadcrumb[] {
  return readBreadcrumbs();
}

/** 清空面包屑 */
export function clearBreadcrumbs() {
  try {
    localStorage.removeItem(BREADCRUMB_KEY);
  } catch {
    // 同上
  }
}

/**
 * 上报错误：输出到 console 并写入面包屑。
 * 注意：不要在此处记录密码、token 等敏感信息。
 */
export function reportError(error: Error, errorInfo?: ErrorInfo) {
  console.error('[ErrorBoundary]', error, errorInfo);
  addBreadcrumb({
    type: 'error',
    message: `${error.name}: ${error.message}`,
    data: { stack: error.stack, componentStack: errorInfo?.componentStack },
  });
}
