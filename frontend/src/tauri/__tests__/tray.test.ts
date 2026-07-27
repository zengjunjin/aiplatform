import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockIsTauri, mockListen, mockUnlisten } = vi.hoisted(() => ({
  mockIsTauri: vi.fn(),
  mockListen: vi.fn(),
  mockUnlisten: vi.fn(),
}));

vi.mock('../../utils/tauri', () => ({
  isTauri: mockIsTauri,
}));

vi.mock('@tauri-apps/api/event', () => ({
  listen: mockListen,
}));

import { useTauriTray } from '../tray';

describe('useTauriTray', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsTauri.mockReturnValue(false);
    mockListen.mockResolvedValue(mockUnlisten);
  });

  it('exposes isTauri and onMenuClick', () => {
    const api = useTauriTray();
    expect(api.isTauri).toBe(mockIsTauri);
    expect(typeof api.onMenuClick).toBe('function');
  });

  describe('onMenuClick', () => {
    it('returns noop and skips listen when not in Tauri', async () => {
      mockIsTauri.mockReturnValue(false);
      const { onMenuClick } = useTauriTray();
      const unlisten = await onMenuClick(vi.fn());
      expect(unlisten).toBeInstanceOf(Function);
      expect(mockListen).not.toHaveBeenCalled();
    });

    it('listens to tray://menu-click event and returns unlisten in Tauri', async () => {
      mockIsTauri.mockReturnValue(true);
      const { onMenuClick } = useTauriTray();
      const unlisten = await onMenuClick(vi.fn());
      expect(mockListen).toHaveBeenCalledWith(
        'tray://menu-click',
        expect.any(Function),
      );
      expect(unlisten).toBe(mockUnlisten);
    });

    it('invokes callback with payload when event fires', async () => {
      mockIsTauri.mockReturnValue(true);
      const cb = vi.fn();
      const { onMenuClick } = useTauriTray();
      await onMenuClick(cb);
      const handler = mockListen.mock.calls[0][1];
      handler({ payload: { id: 'settings' } });
      expect(cb).toHaveBeenCalledWith({ id: 'settings' });
    });

    it('returns noop when listen throws and logs error', async () => {
      mockIsTauri.mockReturnValue(true);
      mockListen.mockRejectedValue(new Error('listen fail'));
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const { onMenuClick } = useTauriTray();
      const unlisten = await onMenuClick(vi.fn());
      expect(unlisten).toBeInstanceOf(Function);
      expect(errSpy).toHaveBeenCalledWith(
        'Tauri tray listen failed:',
        expect.any(Error),
      );
      errSpy.mockRestore();
    });
  });
});
