import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockIsTauri, mockGetCurrentWindow } = vi.hoisted(() => ({
  mockIsTauri: vi.fn(),
  mockGetCurrentWindow: vi.fn(),
}));

vi.mock('../../utils/tauri', () => ({
  isTauri: mockIsTauri,
}));

vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: mockGetCurrentWindow,
}));

import { useTauriWindow } from '../window';

describe('useTauriWindow', () => {
  let mockWin: {
    minimize: ReturnType<typeof vi.fn>;
    maximize: ReturnType<typeof vi.fn>;
    unmaximize: ReturnType<typeof vi.fn>;
    isMaximized: ReturnType<typeof vi.fn>;
    close: ReturnType<typeof vi.fn>;
    setFocus: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockIsTauri.mockReturnValue(false);
    mockWin = {
      minimize: vi.fn(),
      maximize: vi.fn(),
      unmaximize: vi.fn(),
      isMaximized: vi.fn(),
      close: vi.fn(),
      setFocus: vi.fn(),
    };
    mockGetCurrentWindow.mockReturnValue(mockWin);
  });

  it('exposes all window API methods', () => {
    const api = useTauriWindow();
    expect(api.isTauri).toBe(mockIsTauri);
    expect(typeof api.minimize).toBe('function');
    expect(typeof api.toggleMaximize).toBe('function');
    expect(typeof api.close).toBe('function');
    expect(typeof api.setFocused).toBe('function');
  });

  describe('minimize', () => {
    it('skips when not in Tauri', async () => {
      mockIsTauri.mockReturnValue(false);
      const { minimize } = useTauriWindow();
      await minimize();
      expect(mockGetCurrentWindow).not.toHaveBeenCalled();
    });

    it('calls minimize in Tauri', async () => {
      mockIsTauri.mockReturnValue(true);
      const { minimize } = useTauriWindow();
      await minimize();
      expect(mockWin.minimize).toHaveBeenCalled();
    });

    it('logs error when minimize throws', async () => {
      mockIsTauri.mockReturnValue(true);
      mockWin.minimize.mockRejectedValue(new Error('min fail'));
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const { minimize } = useTauriWindow();
      await minimize();
      expect(errSpy).toHaveBeenCalledWith(
        'Tauri minimize failed:',
        expect.any(Error),
      );
      errSpy.mockRestore();
    });
  });

  describe('toggleMaximize', () => {
    it('skips when not in Tauri', async () => {
      mockIsTauri.mockReturnValue(false);
      const { toggleMaximize } = useTauriWindow();
      await toggleMaximize();
      expect(mockGetCurrentWindow).not.toHaveBeenCalled();
    });

    it('calls unmaximize when window is maximized', async () => {
      mockIsTauri.mockReturnValue(true);
      mockWin.isMaximized.mockResolvedValue(true);
      const { toggleMaximize } = useTauriWindow();
      await toggleMaximize();
      expect(mockWin.unmaximize).toHaveBeenCalled();
      expect(mockWin.maximize).not.toHaveBeenCalled();
    });

    it('calls maximize when window is not maximized', async () => {
      mockIsTauri.mockReturnValue(true);
      mockWin.isMaximized.mockResolvedValue(false);
      const { toggleMaximize } = useTauriWindow();
      await toggleMaximize();
      expect(mockWin.maximize).toHaveBeenCalled();
      expect(mockWin.unmaximize).not.toHaveBeenCalled();
    });

    it('logs error when toggleMaximize throws', async () => {
      mockIsTauri.mockReturnValue(true);
      mockWin.isMaximized.mockRejectedValue(new Error('toggle fail'));
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const { toggleMaximize } = useTauriWindow();
      await toggleMaximize();
      expect(errSpy).toHaveBeenCalledWith(
        'Tauri toggleMaximize failed:',
        expect.any(Error),
      );
      errSpy.mockRestore();
    });
  });

  describe('close', () => {
    it('skips when not in Tauri', async () => {
      mockIsTauri.mockReturnValue(false);
      const { close } = useTauriWindow();
      await close();
      expect(mockGetCurrentWindow).not.toHaveBeenCalled();
    });

    it('calls close in Tauri', async () => {
      mockIsTauri.mockReturnValue(true);
      const { close } = useTauriWindow();
      await close();
      expect(mockWin.close).toHaveBeenCalled();
    });

    it('logs error when close throws', async () => {
      mockIsTauri.mockReturnValue(true);
      mockWin.close.mockRejectedValue(new Error('close fail'));
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const { close } = useTauriWindow();
      await close();
      expect(errSpy).toHaveBeenCalledWith(
        'Tauri close failed:',
        expect.any(Error),
      );
      errSpy.mockRestore();
    });
  });

  describe('setFocused', () => {
    it('skips when not in Tauri', async () => {
      mockIsTauri.mockReturnValue(false);
      const { setFocused } = useTauriWindow();
      await setFocused();
      expect(mockGetCurrentWindow).not.toHaveBeenCalled();
    });

    it('calls setFocus in Tauri', async () => {
      mockIsTauri.mockReturnValue(true);
      const { setFocused } = useTauriWindow();
      await setFocused();
      expect(mockWin.setFocus).toHaveBeenCalled();
    });

    it('logs error when setFocus throws', async () => {
      mockIsTauri.mockReturnValue(true);
      mockWin.setFocus.mockRejectedValue(new Error('focus fail'));
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const { setFocused } = useTauriWindow();
      await setFocused();
      expect(errSpy).toHaveBeenCalledWith(
        'Tauri setFocused failed:',
        expect.any(Error),
      );
      errSpy.mockRestore();
    });
  });
});
