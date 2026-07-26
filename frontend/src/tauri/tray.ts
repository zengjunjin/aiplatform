import { isTauri } from '../utils/tauri';

const TAURI_EVENT = '@tauri-apps/api/event';

export interface TrayMenuEvent {
  id: string;
}

export function useTauriTray() {
  return {
    isTauri,
    onMenuClick: async (callback: (event: TrayMenuEvent) => void) => {
      if (!isTauri()) return () => {};
      try {
        const mod = await import(/* @vite-ignore */ TAURI_EVENT);
        const unlisten = await mod.listen<TrayMenuEvent>('tray://menu-click', (e) => {
          callback(e.payload);
        });
        return unlisten;
      } catch (e) {
        console.error('Tauri tray listen failed:', e);
        return () => {};
      }
    },
  };
}
