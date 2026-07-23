import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

describe('tauri utils', () => {
  beforeEach(() => {
    // 确保 isTauri 默认返回 false 的环境
    delete (globalThis as any).__TAURI_INTERNALS__;
    delete (globalThis as any).__TAURI__;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    // 恢复 window 对象上的 Tauri 标记
    delete (globalThis as any).__TAURI_INTERNALS__;
    delete (globalThis as any).__TAURI__;
  });

  describe('isTauri', () => {
    it('should return false in browser environment', async () => {
      const { isTauri } = await import('../../utils/tauri');
      expect(isTauri()).toBe(false);
    });

    it('should return true when __TAURI_INTERNALS__ is present', async () => {
      (globalThis as any).__TAURI_INTERNALS__ = {};
      const { isTauri } = await import('../../utils/tauri');
      expect(isTauri()).toBe(true);
    });

    it('should return true when __TAURI__ is present', async () => {
      (globalThis as any).__TAURI__ = {};
      const { isTauri } = await import('../../utils/tauri');
      expect(isTauri()).toBe(true);
    });

    it('should return true when protocol is tauri:', async () => {
      const original = window.location;
      vi.spyOn(window, 'location', 'get').mockReturnValue({
        ...original,
        protocol: 'tauri:',
        hostname: 'localhost',
      } as any);
      const { isTauri } = await import('../../utils/tauri');
      expect(isTauri()).toBe(true);
    });
  });

  describe('readLocalFile', () => {
    it('should return null in non-Tauri environment', async () => {
      const { readLocalFile } = await import('../../utils/tauri');
      const result = await readLocalFile('/some/path/file.txt');
      expect(result).toBeNull();
    });

    it('should return null when filePath is not provided in non-Tauri', async () => {
      const { readLocalFile } = await import('../../utils/tauri');
      const result = await readLocalFile(undefined);
      expect(result).toBeNull();
    });

    it('should return null and log error when Tauri fs read fails', async () => {
      (globalThis as any).__TAURI_INTERNALS__ = {};
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
      vi.doMock('@tauri-apps/api/fs', () => ({
        readBinaryFile: vi.fn().mockRejectedValue(new Error('fs error')),
      }));

      const { readLocalFile } = await import('../../utils/tauri');
      const result = await readLocalFile('/path/file.txt');
      expect(result).toBeNull();
      expect(spy).toHaveBeenCalled();
      spy.mockRestore();
      vi.doUnmock('@tauri-apps/api/fs');
    });
  });

  describe('getAppDataDir', () => {
    it('should return null in non-Tauri environment', async () => {
      const { getAppDataDir } = await import('../../utils/tauri');
      const result = await getAppDataDir();
      expect(result).toBeNull();
    });
  });

  describe('setWindowTitle', () => {
    it('should do nothing in non-Tauri environment', async () => {
      const { setWindowTitle } = await import('../../utils/tauri');
      await expect(setWindowTitle('test')).resolves.toBeUndefined();
    });
  });

  describe('closeWindow', () => {
    it('should do nothing in non-Tauri environment', async () => {
      const { closeWindow } = await import('../../utils/tauri');
      await expect(closeWindow()).resolves.toBeUndefined();
    });
  });
});
