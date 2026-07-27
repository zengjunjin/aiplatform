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

import { useDeepLink } from '../deepLink';

describe('useDeepLink', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsTauri.mockReturnValue(false);
    mockListen.mockResolvedValue(mockUnlisten);
  });

  it('exposes isTauri, onDeepLink, navigateToRoute', () => {
    const api = useDeepLink();
    expect(api.isTauri).toBe(mockIsTauri);
    expect(typeof api.onDeepLink).toBe('function');
    expect(typeof api.navigateToRoute).toBe('function');
  });

  describe('navigateToRoute', () => {
    it.each([
      [{ route: 'kb', id: '123' }, '/kb/123'],
      [{ route: 'kb' }, '/kb'],
      [{ route: 'kb', id: undefined }, '/kb'],
      [{ route: 'chat', id: 'abc' }, '/chat/abc'],
      [{ route: 'chat' }, '/chat'],
      [{ route: 'login' }, '/login'],
      [{ route: 'settings' }, '/settings'],
      [{ route: 'unknown' }, '/'],
      [{ route: '' }, '/'],
    ])('returns %s for payload %j', (payload, expected) => {
      const { navigateToRoute } = useDeepLink();
      expect(navigateToRoute(payload as any)).toBe(expected);
    });
  });

  describe('onDeepLink', () => {
    it('returns noop and skips listen when not in Tauri', async () => {
      mockIsTauri.mockReturnValue(false);
      const { onDeepLink } = useDeepLink();
      const unlisten = await onDeepLink(vi.fn());
      expect(unlisten).toBeInstanceOf(Function);
      expect(mockListen).not.toHaveBeenCalled();
    });

    it('listens to deep-link event and returns unlisten in Tauri', async () => {
      mockIsTauri.mockReturnValue(true);
      const { onDeepLink } = useDeepLink();
      const unlisten = await onDeepLink(vi.fn());
      expect(mockListen).toHaveBeenCalledWith('deep-link', expect.any(Function));
      expect(unlisten).toBe(mockUnlisten);
    });

    it('invokes callback with payload when event fires', async () => {
      mockIsTauri.mockReturnValue(true);
      const cb = vi.fn();
      const { onDeepLink } = useDeepLink();
      await onDeepLink(cb);
      const handler = mockListen.mock.calls[0][1];
      handler({ payload: { route: 'kb', id: '1' } });
      expect(cb).toHaveBeenCalledWith({ route: 'kb', id: '1' });
    });

    it('returns noop when listen throws and logs error', async () => {
      mockIsTauri.mockReturnValue(true);
      mockListen.mockRejectedValue(new Error('listen fail'));
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const { onDeepLink } = useDeepLink();
      const unlisten = await onDeepLink(vi.fn());
      expect(unlisten).toBeInstanceOf(Function);
      expect(errSpy).toHaveBeenCalledWith(
        'Tauri deep-link listen failed:',
        expect.any(Error),
      );
      errSpy.mockRestore();
    });
  });
});
