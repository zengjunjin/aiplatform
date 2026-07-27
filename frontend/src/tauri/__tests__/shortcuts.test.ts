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

import { useGlobalShortcuts } from '../shortcuts';

describe('useGlobalShortcuts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsTauri.mockReturnValue(false);
    mockListen.mockResolvedValue(mockUnlisten);
  });

  it('exposes isTauri and onShortcut', () => {
    const api = useGlobalShortcuts();
    expect(api.isTauri).toBe(mockIsTauri);
    expect(typeof api.onShortcut).toBe('function');
  });

  describe('onShortcut', () => {
    it('returns noop and skips listen when not in Tauri', async () => {
      mockIsTauri.mockReturnValue(false);
      const { onShortcut } = useGlobalShortcuts();
      const unlisten = await onShortcut(vi.fn());
      expect(unlisten).toBeInstanceOf(Function);
      expect(mockListen).not.toHaveBeenCalled();
    });

    it('listens to shortcut event and returns unlisten in Tauri', async () => {
      mockIsTauri.mockReturnValue(true);
      const { onShortcut } = useGlobalShortcuts();
      const unlisten = await onShortcut(vi.fn());
      expect(mockListen).toHaveBeenCalledWith('shortcut', expect.any(Function));
      expect(unlisten).toBe(mockUnlisten);
    });

    it('invokes callback with payload when event fires', async () => {
      mockIsTauri.mockReturnValue(true);
      const cb = vi.fn();
      const { onShortcut } = useGlobalShortcuts();
      await onShortcut(cb);
      const handler = mockListen.mock.calls[0][1];
      const payload = { action: 'new_chat' as const };
      handler({ payload });
      expect(cb).toHaveBeenCalledWith(payload);
    });

    it('supports all shortcut action types', async () => {
      mockIsTauri.mockReturnValue(true);
      const cb = vi.fn();
      const { onShortcut } = useGlobalShortcuts();
      await onShortcut(cb);
      const handler = mockListen.mock.calls[0][1];
      for (const action of ['open_search', 'new_chat', 'toggle_devtools'] as const) {
        cb.mockClear();
        handler({ payload: { action } });
        expect(cb).toHaveBeenCalledWith({ action });
      }
    });

    it('returns noop when listen throws and logs error', async () => {
      mockIsTauri.mockReturnValue(true);
      mockListen.mockRejectedValue(new Error('listen fail'));
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const { onShortcut } = useGlobalShortcuts();
      const unlisten = await onShortcut(vi.fn());
      expect(unlisten).toBeInstanceOf(Function);
      expect(errSpy).toHaveBeenCalledWith(
        'Tauri shortcut listen failed:',
        expect.any(Error),
      );
      errSpy.mockRestore();
    });
  });
});
