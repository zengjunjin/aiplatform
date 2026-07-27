import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const { mockIsTauri, mockCheck, mockDownloadAndInstall } = vi.hoisted(() => ({
  mockIsTauri: vi.fn(),
  mockCheck: vi.fn(),
  mockDownloadAndInstall: vi.fn(),
}));

vi.mock('../../utils/tauri', () => ({
  isTauri: mockIsTauri,
}));

vi.mock('@tauri-apps/plugin-updater', () => ({
  check: mockCheck,
}));

import { useUpdater } from '../updater';

describe('useUpdater', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsTauri.mockReturnValue(false);
  });

  it('exposes isTauri, checkForUpdate, installUpdate, autoCheckAfter5s', () => {
    const api = useUpdater();
    expect(api.isTauri).toBe(mockIsTauri);
    expect(typeof api.checkForUpdate).toBe('function');
    expect(typeof api.installUpdate).toBe('function');
    expect(typeof api.autoCheckAfter5s).toBe('function');
  });

  describe('checkForUpdate', () => {
    it('returns null when not in Tauri', async () => {
      mockIsTauri.mockReturnValue(false);
      const { checkForUpdate } = useUpdater();
      expect(await checkForUpdate()).toBeNull();
      expect(mockCheck).not.toHaveBeenCalled();
    });

    it('returns UpdateInfo when update available', async () => {
      mockIsTauri.mockReturnValue(true);
      mockCheck.mockResolvedValue({
        version: '1.2.0',
        date: '2026-01-01',
        body: 'release notes',
        downloadAndInstall: mockDownloadAndInstall,
      });
      const { checkForUpdate } = useUpdater();
      const info = await checkForUpdate();
      expect(info).toEqual({
        version: '1.2.0',
        date: '2026-01-01',
        body: 'release notes',
      });
    });

    it('returns null when no update available', async () => {
      mockIsTauri.mockReturnValue(true);
      mockCheck.mockResolvedValue(null);
      const { checkForUpdate } = useUpdater();
      expect(await checkForUpdate()).toBeNull();
    });

    it('returns null and logs error when check throws', async () => {
      mockIsTauri.mockReturnValue(true);
      mockCheck.mockRejectedValue(new Error('check fail'));
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const { checkForUpdate } = useUpdater();
      expect(await checkForUpdate()).toBeNull();
      expect(errSpy).toHaveBeenCalledWith(
        'Tauri update check failed:',
        expect.any(Error),
      );
      errSpy.mockRestore();
    });
  });

  describe('installUpdate', () => {
    it('returns false when not in Tauri', async () => {
      mockIsTauri.mockReturnValue(false);
      const { installUpdate } = useUpdater();
      expect(await installUpdate()).toBe(false);
      expect(mockCheck).not.toHaveBeenCalled();
    });

    it('calls downloadAndInstall and returns true when update available', async () => {
      mockIsTauri.mockReturnValue(true);
      mockCheck.mockResolvedValue({
        version: '1.2.0',
        date: '2026-01-01',
        body: 'release notes',
        downloadAndInstall: mockDownloadAndInstall,
      });
      const { installUpdate } = useUpdater();
      expect(await installUpdate()).toBe(true);
      expect(mockDownloadAndInstall).toHaveBeenCalled();
    });

    it('returns false when no update available', async () => {
      mockIsTauri.mockReturnValue(true);
      mockCheck.mockResolvedValue(null);
      const { installUpdate } = useUpdater();
      expect(await installUpdate()).toBe(false);
    });

    it('returns false and logs error when install throws', async () => {
      mockIsTauri.mockReturnValue(true);
      mockCheck.mockRejectedValue(new Error('install fail'));
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const { installUpdate } = useUpdater();
      expect(await installUpdate()).toBe(false);
      expect(errSpy).toHaveBeenCalledWith(
        'Tauri update install failed:',
        expect.any(Error),
      );
      errSpy.mockRestore();
    });
  });

  describe('autoCheckAfter5s', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    it('does nothing when not in Tauri', async () => {
      mockIsTauri.mockReturnValue(false);
      const { autoCheckAfter5s } = useUpdater();
      const onUpdate = vi.fn();
      await autoCheckAfter5s(onUpdate);
      await vi.advanceTimersByTimeAsync(5000);
      expect(mockCheck).not.toHaveBeenCalled();
      expect(onUpdate).not.toHaveBeenCalled();
    });

    it('schedules check after 5s and calls onUpdate when update available', async () => {
      mockIsTauri.mockReturnValue(true);
      mockCheck.mockResolvedValue({
        version: '2.0.0',
        date: '2026-07-27',
        body: 'major release',
        downloadAndInstall: vi.fn(),
      });
      const { autoCheckAfter5s } = useUpdater();
      const onUpdate = vi.fn();
      await autoCheckAfter5s(onUpdate);
      expect(mockCheck).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(5000);
      expect(mockCheck).toHaveBeenCalled();
      expect(onUpdate).toHaveBeenCalledWith({
        version: '2.0.0',
        date: '2026-07-27',
        body: 'major release',
      });
    });

    it('does not call onUpdate when no update available', async () => {
      mockIsTauri.mockReturnValue(true);
      mockCheck.mockResolvedValue(null);
      const { autoCheckAfter5s } = useUpdater();
      const onUpdate = vi.fn();
      await autoCheckAfter5s(onUpdate);
      await vi.advanceTimersByTimeAsync(5000);
      expect(onUpdate).not.toHaveBeenCalled();
    });

    it('skips second call due to checked guard (same instance)', async () => {
      mockIsTauri.mockReturnValue(true);
      mockCheck.mockResolvedValue(null);
      const api = useUpdater();
      const onUpdate = vi.fn();
      await api.autoCheckAfter5s(onUpdate);
      await api.autoCheckAfter5s(onUpdate);
      await vi.advanceTimersByTimeAsync(5000);
      expect(mockCheck).toHaveBeenCalledTimes(1);
    });

    it('logs error when check throws inside timer', async () => {
      mockIsTauri.mockReturnValue(true);
      mockCheck.mockRejectedValue(new Error('auto fail'));
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const { autoCheckAfter5s } = useUpdater();
      await autoCheckAfter5s(vi.fn());
      await vi.advanceTimersByTimeAsync(5000);
      expect(errSpy).toHaveBeenCalledWith(
        'Tauri auto update check failed:',
        expect.any(Error),
      );
      errSpy.mockRestore();
    });

    it('works without onUpdate callback', async () => {
      mockIsTauri.mockReturnValue(true);
      mockCheck.mockResolvedValue({
        version: '1.0.1',
        date: '2026-01-01',
        body: 'patch',
        downloadAndInstall: vi.fn(),
      });
      const { autoCheckAfter5s } = useUpdater();
      await autoCheckAfter5s();
      await vi.advanceTimersByTimeAsync(5000);
      expect(mockCheck).toHaveBeenCalled();
    });
  });
});
