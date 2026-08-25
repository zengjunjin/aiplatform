import { useCallback } from 'react';
import { App as AntdApp } from 'antd';
import { useTranslation } from 'react-i18next';
import { getErrorMessage, isAuthExpiredError } from '../utils/errorReporter';

/**
 * 统一 API 调用 toast 反馈 hook (Task 5.8)
 * 替换各页面中重复的 try/catch + message.success/error 模板代码
 *
 * 会话失效抑制：错误带 isAuthExpired 标记（client.ts 401→refresh 失败路径）
 * 时不弹 "XX加载失败" toast——会话失效瞬间多路并发加载各自弹错，
 * 跳转登录页后堆积成噪音；统一的 "登录已过期" 提示由 auth store 弹出。
 */
export function useApiToast() {
  const { t } = useTranslation();
  const { message } = AntdApp.useApp();
  const runWithToast = useCallback(async <T,>(
    fn: () => Promise<T>,
    opts: {
      successKey: string;
      errorKey: string;
      onSuccess?: (result: T) => void;
    }
  ): Promise<T | undefined> => {
    try {
      const result = await fn();
      message.success(t(opts.successKey));
      opts.onSuccess?.(result);
      return result;
    } catch (e: unknown) {
      if (!isAuthExpiredError(e)) {
        message.error(getErrorMessage(e) || t(opts.errorKey));
      }
      return undefined;
    }
  }, [t, message]);

  /**
   * Task 51: 与 runWithToast 并存的变体 — 失败时补充 toast 但仍 throw 原始错误,
   * 供需要在 catch 中继续处理 (如表单校验、状态回滚) 的调用方使用。
   * 成功行为与 runWithToast 一致 (弹出 success toast, 可选 onSuccess 回调)。
   */
  const runWithToastOrThrow = useCallback(async <T,>(
    fn: () => Promise<T>,
    opts: {
      successKey: string;
      errorKey: string;
      onSuccess?: (result: T) => void;
    }
  ): Promise<T> => {
    try {
      const result = await fn();
      message.success(t(opts.successKey));
      opts.onSuccess?.(result);
      return result;
    } catch (e: unknown) {
      if (!isAuthExpiredError(e)) {
        message.error(getErrorMessage(e) || t(opts.errorKey));
      }
      throw e;
    }
  }, [t, message]);

  /**
   * Task 6.1: 直接弹出 error toast, 用于非 runWithToast 场景下的错误提示
   * (如并行 Promise.allSettled 中单个任务失败的轻量提示)。
   * e 可选：传入时若为会话失效错误则静默抑制。
   */
  const error = useCallback((msg: string, e?: unknown) => {
    if (e !== undefined && isAuthExpiredError(e)) return;
    message.error(msg);
  }, [message]);

  return { runWithToast, runWithToastOrThrow, error };
}
