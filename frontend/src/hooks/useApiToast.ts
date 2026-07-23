import { useCallback } from 'react';
import { App as AntdApp } from 'antd';
import { useTranslation } from 'react-i18next';
import { getErrorMessage } from '../utils/errorReporter';

/**
 * 统一 API 调用 toast 反馈 hook (Task 5.8)
 * 替换各页面中重复的 try/catch + message.success/error 模板代码
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
      message.error(getErrorMessage(e) || t(opts.errorKey));
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
      message.error(getErrorMessage(e) || t(opts.errorKey));
      throw e;
    }
  }, [t, message]);

  return { runWithToast, runWithToastOrThrow };
}
