/** Tauri API 封装 */

import { logger } from './logger';

export const isTauri = (): boolean => {
  if (typeof window === 'undefined') return false;

  // Tauri 2.0 在 window 上挂载 __TAURI_INTERNALS__
  if ('__TAURI_INTERNALS__' in window || '__TAURI__' in window) {
    return true;
  }

  // 检测 Tauri 自定义协议
  try {
    if (window.location?.protocol === 'tauri:') return true;
  } catch {
    // window.location 在某些环境不可访问
  }

  // 兜底：Tauri 默认加载的页面 hostname 为 tauri.localhost
  try {
    if (window.location?.hostname === 'tauri.localhost') return true;
  } catch {
    // window.location 在某些环境不可访问
  }

  return false;
};

// 使用变量名让 Vite 不在构建时预解析
const TAURI_FS = '@tauri-apps/api/fs';
const TAURI_PATH = '@tauri-apps/api/path';
const TAURI_WINDOW = '@tauri-apps/api/window';

export async function readLocalFile(filePath?: string): Promise<File | null> {
  if (isTauri() && filePath) {
    try {
      const mod = await import(/* @vite-ignore */ TAURI_FS);
      const data = await mod.readBinaryFile(filePath);
      const name = filePath.split(/[\\/]/).pop() || 'file';
      return new File([data], name);
    } catch (e) {
      logger.error('Tauri fs read failed:', e);
      return null;
    }
  }
  return null;
}

export async function getAppDataDir(): Promise<string | null> {
  if (!isTauri()) return null;
  try {
    const mod = await import(/* @vite-ignore */ TAURI_PATH);
    return await mod.appDataDir();
  } catch {
    return null;
  }
}

export async function setWindowTitle(title: string): Promise<void> {
  if (!isTauri()) return;
  try {
    const mod = await import(/* @vite-ignore */ TAURI_WINDOW);
    await mod.getCurrentWindow().setTitle(title);
  } catch {
    // ignore
  }
}

export async function closeWindow(): Promise<void> {
  if (!isTauri()) return;
  try {
    const mod = await import(/* @vite-ignore */ TAURI_WINDOW);
    await mod.getCurrentWindow().close();
  } catch {
    // ignore
  }
}
