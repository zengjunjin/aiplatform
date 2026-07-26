import { isTauri } from '../utils/tauri';
import type { TauriWindowAPI } from './types';

const TAURI_WINDOW = '@tauri-apps/api/window';

export function useTauriWindow(): TauriWindowAPI {
  return {
    isTauri,
    minimize: async () => {
      if (!isTauri()) return;
      try {
        const mod = await import(/* @vite-ignore */ TAURI_WINDOW);
        await mod.getCurrentWindow().minimize();
      } catch (e) {
        console.error('Tauri minimize failed:', e);
      }
    },
    toggleMaximize: async () => {
      if (!isTauri()) return;
      try {
        const mod = await import(/* @vite-ignore */ TAURI_WINDOW);
        const win = mod.getCurrentWindow();
        if (await win.isMaximized()) {
          await win.unmaximize();
        } else {
          await win.maximize();
        }
      } catch (e) {
        console.error('Tauri toggleMaximize failed:', e);
      }
    },
    close: async () => {
      if (!isTauri()) return;
      try {
        const mod = await import(/* @vite-ignore */ TAURI_WINDOW);
        await mod.getCurrentWindow().close();
      } catch (e) {
        console.error('Tauri close failed:', e);
      }
    },
    setFocused: async () => {
      if (!isTauri()) return;
      try {
        const mod = await import(/* @vite-ignore */ TAURI_WINDOW);
        await mod.getCurrentWindow().setFocus();
      } catch (e) {
        console.error('Tauri setFocused failed:', e);
      }
    },
  };
}
