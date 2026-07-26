import { isTauri } from '../utils/tauri';

const TAURI_EVENT = '@tauri-apps/api/event';

export interface ShortcutEvent {
  action: 'open_search' | 'new_chat' | 'toggle_devtools';
}

export function useGlobalShortcuts() {
  return {
    isTauri,
    onShortcut: async (callback: (event: ShortcutEvent) => void) => {
      if (!isTauri()) return () => {};
      try {
        const mod = await import(/* @vite-ignore */ TAURI_EVENT);
        const unlisten = await mod.listen('shortcut', (e: { payload: ShortcutEvent }) => {
          callback(e.payload);
        });
        return unlisten;
      } catch (e) {
        console.error('Tauri shortcut listen failed:', e);
        return () => {};
      }
    },
  };
}
