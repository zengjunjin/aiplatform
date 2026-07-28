import { isTauri } from '../utils/tauri';

const TAURI_UPDATER = '@tauri-apps/plugin-updater';

export interface UpdateInfo {
  version: string;
  date?: string;
  body: string;
}

// Task 38 (P1-FE-11): 保存 auto check 定时器句柄, 供 cancelAutoCheck 清理
let autoCheckTimer: ReturnType<typeof setTimeout> | null = null;

/** 取消尚未触发的自动更新检查定时器 (组件卸载或页面关闭时调用) */
export function cancelAutoCheck() {
  if (autoCheckTimer) {
    clearTimeout(autoCheckTimer);
    autoCheckTimer = null;
  }
}

export function useUpdater() {
  let checked = false;

  return {
    isTauri,
    checkForUpdate: async (): Promise<UpdateInfo | null> => {
      if (!isTauri()) return null;
      try {
        const mod = await import(/* @vite-ignore */ TAURI_UPDATER);
        const update = await mod.check();
        if (update) {
          return {
            version: update.version,
            date: update.date,
            body: update.body,
          };
        }
        return null;
      } catch (e) {
        console.error('Tauri update check failed:', e);
        return null;
      }
    },
    installUpdate: async (): Promise<boolean> => {
      if (!isTauri()) return false;
      try {
        const mod = await import(/* @vite-ignore */ TAURI_UPDATER);
        const update = await mod.check();
        if (update) {
          await update.downloadAndInstall();
          return true;
        }
        return false;
      } catch (e) {
        console.error('Tauri update install failed:', e);
        return false;
      }
    },
    autoCheckAfter5s: async (onUpdate?: (info: UpdateInfo) => void) => {
      if (!isTauri() || checked) return;
      checked = true;
      if (autoCheckTimer) clearTimeout(autoCheckTimer);
      autoCheckTimer = setTimeout(async () => {
        autoCheckTimer = null;
        if (!isTauri()) return;
        try {
          const mod = await import(/* @vite-ignore */ TAURI_UPDATER);
          const update = await mod.check();
          if (update && onUpdate) {
            onUpdate({
              version: update.version,
              date: update.date,
              body: update.body,
            });
          }
        } catch (e) {
          console.error('Tauri auto update check failed:', e);
        }
      }, 5000);
    },
    cancelAutoCheck,
  };
}
