import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

/**
 * T14: logger 工具单元测试
 *
 * 源码:
 *   const isDev = import.meta.env.DEV;
 *   export const logger = {
 *     debug: (...args) => isDev && console.debug(...args),
 *     info:  (...args) => isDev && console.info(...args),
 *     warn:  (...args) => console.warn(...args),
 *     error: (...args) => console.error(...args),
 *   };
 *
 * 关键点: `isDev` 在模块加载时一次性求值。要测试 DEV=false 分支必须
 * vi.resetModules() + vi.stubEnv('DEV', false) + 动态 import 重新求值。
 */
describe('logger', () => {
  let debugSpy: ReturnType<typeof vi.spyOn>;
  let infoSpy: ReturnType<typeof vi.spyOn>;
  let warnSpy: ReturnType<typeof vi.spyOn>;
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    debugSpy = vi.spyOn(console, 'debug').mockImplementation(() => {});
    infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  describe('DEV 模式 (import.meta.env.DEV = true)', () => {
    beforeEach(() => {
      vi.stubEnv('DEV', true);
    });

    it('debug 应调用 console.debug 并透传所有参数', async () => {
      const { logger } = await import('../../utils/logger');
      logger.debug('hello', 1, { a: 1 });
      expect(debugSpy).toHaveBeenCalledTimes(1);
      expect(debugSpy).toHaveBeenCalledWith('hello', 1, { a: 1 });
    });

    it('info 应调用 console.info 并透传所有参数', async () => {
      const { logger } = await import('../../utils/logger');
      logger.info('info msg', [1, 2]);
      expect(infoSpy).toHaveBeenCalledTimes(1);
      expect(infoSpy).toHaveBeenCalledWith('info msg', [1, 2]);
    });

    it('warn 应调用 console.warn 并透传所有参数', async () => {
      const { logger } = await import('../../utils/logger');
      logger.warn('warn msg');
      expect(warnSpy).toHaveBeenCalledTimes(1);
      expect(warnSpy).toHaveBeenCalledWith('warn msg');
    });

    it('error 应调用 console.error 并透传所有参数', async () => {
      const { logger } = await import('../../utils/logger');
      logger.error('error msg', new Error('boom'));
      expect(errorSpy).toHaveBeenCalledTimes(1);
      expect(errorSpy).toHaveBeenCalledWith('error msg', expect.any(Error));
    });

    it('debug 支持无参数调用', async () => {
      const { logger } = await import('../../utils/logger');
      logger.debug();
      expect(debugSpy).toHaveBeenCalledTimes(1);
      expect(debugSpy).toHaveBeenCalledWith();
    });

    it('info 支持多种类型参数 (null/undefined/number)', async () => {
      const { logger } = await import('../../utils/logger');
      logger.info(null, undefined, 0, '');
      expect(infoSpy).toHaveBeenCalledWith(null, undefined, 0, '');
    });

    it('warn 支持对象参数', async () => {
      const { logger } = await import('../../utils/logger');
      const obj = { code: 500, detail: { reason: 'crash' } };
      logger.warn(obj);
      expect(warnSpy).toHaveBeenCalledWith(obj);
    });

    it('error 支持多参数透传', async () => {
      const { logger } = await import('../../utils/logger');
      logger.error('prefix', { a: 1 }, [1, 2], 'suffix');
      expect(errorSpy).toHaveBeenCalledWith('prefix', { a: 1 }, [1, 2], 'suffix');
    });
  });

  describe('PROD 模式 (import.meta.env.DEV = false)', () => {
    beforeEach(() => {
      vi.stubEnv('DEV', false);
    });

    it('debug 不应调用 console.debug', async () => {
      const { logger } = await import('../../utils/logger');
      logger.debug('should not log');
      expect(debugSpy).not.toHaveBeenCalled();
    });

    it('info 不应调用 console.info', async () => {
      const { logger } = await import('../../utils/logger');
      logger.info('should not log');
      expect(infoSpy).not.toHaveBeenCalled();
    });

    it('warn 仍应调用 console.warn (warn 不受 isDev 控制)', async () => {
      const { logger } = await import('../../utils/logger');
      logger.warn('should still log');
      expect(warnSpy).toHaveBeenCalledTimes(1);
      expect(warnSpy).toHaveBeenCalledWith('should still log');
    });

    it('error 仍应调用 console.error (error 不受 isDev 控制)', async () => {
      const { logger } = await import('../../utils/logger');
      logger.error('should still log');
      expect(errorSpy).toHaveBeenCalledTimes(1);
      expect(errorSpy).toHaveBeenCalledWith('should still log');
    });

    it('debug 返回 false (短路求值)', async () => {
      const { logger } = await import('../../utils/logger');
      const result = logger.debug('x');
      expect(result).toBe(false);
    });

    it('info 返回 false (短路求值)', async () => {
      const { logger } = await import('../../utils/logger');
      const result = logger.info('x');
      expect(result).toBe(false);
    });
  });

  describe('传输一致性 (透传)', () => {
    beforeEach(() => {
      vi.stubEnv('DEV', true);
    });

    it('多参数透传顺序保持一致', async () => {
      const { logger } = await import('../../utils/logger');
      logger.debug('a', 'b', 'c', 'd', 'e');
      expect(debugSpy).toHaveBeenCalledWith('a', 'b', 'c', 'd', 'e');
    });

    it('error 透传 Error 对象', async () => {
      const { logger } = await import('../../utils/logger');
      const err = new TypeError('type error');
      logger.error(err);
      expect(errorSpy).toHaveBeenCalledWith(err);
    });
  });
});
