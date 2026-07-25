/**
 * useApiToast hook 单元测试。
 *
 * 测试目的：覆盖统一 API toast 反馈 hook 的核心分支——
 *   1. runWithToast 成功路径：message.success(t(successKey)) + onSuccess(result) + 返回 result
 *   2. runWithToast 失败路径：message.error(getErrorMessage(e) || t(errorKey)) + 返回 undefined
 *      覆盖 || 回退分支（空 message Error → 回退 errorKey）、字符串错误、axios 风格错误码
 *      （400/401/403/404/429/500）、网络错误、超时错误
 *   3. runWithToastOrThrow 成功路径（同 runWithToast）
 *   4. runWithToastOrThrow 失败路径：message.error + 重新抛出原始错误
 *   5. error(msg)：直接调用 message.error
 *   6. onSuccess 可选（缺失时不抛错）
 *
 * 当前分支覆盖率为 0%，本测试旨在覆盖 try/catch 与 || 回退分支。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useApiToast } from './useApiToast';

// Stable t + message mocks（vi.hoisted 保证引用稳定，避免 useCallback 依赖无限重建）
const { mockT, mockMessage } = vi.hoisted(() => ({
  mockT: (key: string) => key,
  mockMessage: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...(actual as any),
    App: Object.assign((actual as any).App, {
      useApp: () => ({ message: mockMessage }),
    }),
  };
});

// Mock getErrorMessage 以隔离 errorReporter 的 logger 副作用，行为与真实实现一致
vi.mock('../utils/errorReporter', () => ({
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));

describe('useApiToast', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('runWithToast', () => {
    it('should call message.success and onSuccess and return result on success', async () => {
      const { result } = renderHook(() => useApiToast());
      const onSuccess = vi.fn();
      const fn = vi.fn().mockResolvedValue({ id: 1 });

      let ret: unknown;
      await act(async () => {
        ret = await result.current.runWithToast(fn, {
          successKey: 'ok',
          errorKey: 'err',
          onSuccess,
        });
      });

      expect(mockMessage.success).toHaveBeenCalledWith('ok');
      expect(onSuccess).toHaveBeenCalledWith({ id: 1 });
      expect(ret).toEqual({ id: 1 });
    });

    it('should work without onSuccess callback', async () => {
      const { result } = renderHook(() => useApiToast());
      const fn = vi.fn().mockResolvedValue('val');

      let ret: unknown;
      await act(async () => {
        ret = await result.current.runWithToast(fn, { successKey: 'ok', errorKey: 'err' });
      });

      expect(mockMessage.success).toHaveBeenCalledWith('ok');
      expect(ret).toBe('val');
    });

    it('should call message.error with error message and return undefined on failure', async () => {
      const { result } = renderHook(() => useApiToast());
      const fn = vi.fn().mockRejectedValue(new Error('boom'));

      let ret: unknown;
      await act(async () => {
        ret = await result.current.runWithToast(fn, { successKey: 'ok', errorKey: 'err' });
      });

      expect(mockMessage.error).toHaveBeenCalledWith('boom');
      expect(ret).toBeUndefined();
    });

    it('should fall back to errorKey when error message is empty', async () => {
      const { result } = renderHook(() => useApiToast());
      // getErrorMessage(new Error('')) === '' → falsy → 回退 t(errorKey)
      const fn = vi.fn().mockRejectedValue(new Error(''));

      let ret: unknown;
      await act(async () => {
        ret = await result.current.runWithToast(fn, {
          successKey: 'ok',
          errorKey: 'fallback',
        });
      });

      expect(mockMessage.error).toHaveBeenCalledWith('fallback');
      expect(ret).toBeUndefined();
    });

    it('should handle string error via getErrorMessage', async () => {
      const { result } = renderHook(() => useApiToast());
      const fn = vi.fn().mockRejectedValue('plain string error');

      await act(async () => {
        await result.current.runWithToast(fn, { successKey: 'ok', errorKey: 'err' });
      });

      expect(mockMessage.error).toHaveBeenCalledWith('plain string error');
    });

    it('should handle axios-style errors with various status codes', async () => {
      const codes = [400, 401, 403, 404, 429, 500];
      for (const code of codes) {
        const { result } = renderHook(() => useApiToast());
        const err = Object.assign(
          new Error(`Request failed with status code ${code}`),
          { response: { status: code, data: { detail: `err-${code}` } } },
        );
        const fn = vi.fn().mockRejectedValue(err);

        let ret: unknown;
        await act(async () => {
          ret = await result.current.runWithToast(fn, {
            successKey: 'ok',
            errorKey: 'err',
          });
        });

        expect(mockMessage.error).toHaveBeenCalledWith(
          `Request failed with status code ${code}`,
        );
        expect(ret).toBeUndefined();
      }
    });

    it('should handle network error', async () => {
      const { result } = renderHook(() => useApiToast());
      const fn = vi.fn().mockRejectedValue(new Error('Network Error'));

      await act(async () => {
        await result.current.runWithToast(fn, { successKey: 'ok', errorKey: 'err' });
      });

      expect(mockMessage.error).toHaveBeenCalledWith('Network Error');
    });

    it('should handle timeout error', async () => {
      const { result } = renderHook(() => useApiToast());
      const err = Object.assign(new Error('timeout of 5000ms exceeded'), {
        code: 'ECONNABORTED',
      });
      const fn = vi.fn().mockRejectedValue(err);

      await act(async () => {
        await result.current.runWithToast(fn, { successKey: 'ok', errorKey: 'err' });
      });

      expect(mockMessage.error).toHaveBeenCalledWith('timeout of 5000ms exceeded');
    });
  });

  describe('runWithToastOrThrow', () => {
    it('should call message.success and return result on success', async () => {
      const { result } = renderHook(() => useApiToast());
      const onSuccess = vi.fn();
      const fn = vi.fn().mockResolvedValue(42);

      let ret: unknown;
      await act(async () => {
        ret = await result.current.runWithToastOrThrow(fn, {
          successKey: 'ok',
          errorKey: 'err',
          onSuccess,
        });
      });

      expect(mockMessage.success).toHaveBeenCalledWith('ok');
      expect(onSuccess).toHaveBeenCalledWith(42);
      expect(ret).toBe(42);
    });

    it('should call message.error and rethrow on failure', async () => {
      const { result } = renderHook(() => useApiToast());
      const fn = vi.fn().mockRejectedValue(new Error('fail'));
      const onSuccess = vi.fn();

      await act(async () => {
        await expect(
          result.current.runWithToastOrThrow(fn, {
            successKey: 'ok',
            errorKey: 'err',
            onSuccess,
          }),
        ).rejects.toThrow('fail');
      });

      expect(mockMessage.error).toHaveBeenCalledWith('fail');
      expect(onSuccess).not.toHaveBeenCalled();
    });

    it('should fall back to errorKey when error message is empty', async () => {
      const { result } = renderHook(() => useApiToast());
      const fn = vi.fn().mockRejectedValue(new Error(''));

      await act(async () => {
        await expect(
          result.current.runWithToastOrThrow(fn, {
            successKey: 'ok',
            errorKey: 'fallback',
          }),
        ).rejects.toThrow('');
      });

      expect(mockMessage.error).toHaveBeenCalledWith('fallback');
    });
  });

  describe('error', () => {
    it('should call message.error with given message', () => {
      const { result } = renderHook(() => useApiToast());
      result.current.error('direct error');
      expect(mockMessage.error).toHaveBeenCalledWith('direct error');
    });
  });
});
