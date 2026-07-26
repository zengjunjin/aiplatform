import { isTauri } from '../utils/tauri';

const TAURI_EVENT = '@tauri-apps/api/event';

export interface DeepLinkPayload {
  route: string;
  id?: string;
}

export function useDeepLink() {
  return {
    isTauri,
    onDeepLink: async (callback: (payload: DeepLinkPayload) => void) => {
      if (!isTauri()) return () => {};
      try {
        const mod = await import(/* @vite-ignore */ TAURI_EVENT);
        const unlisten = await mod.listen<DeepLinkPayload>('deep-link', (e) => {
          callback(e.payload);
        });
        return unlisten;
      } catch (e) {
        console.error('Tauri deep-link listen failed:', e);
        return () => {};
      }
    },
    navigateToRoute: (payload: DeepLinkPayload): string => {
      // 返回 React Router 应跳转的路径
      switch (payload.route) {
        case 'kb':
          return payload.id ? `/kb/${payload.id}` : '/kb';
        case 'chat':
          return payload.id ? `/chat/${payload.id}` : '/chat';
        case 'login':
          return '/login';
        case 'settings':
          return '/settings';
        default:
          return '/';
      }
    },
  };
}
