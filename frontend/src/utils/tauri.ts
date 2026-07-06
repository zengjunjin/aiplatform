/** Tauri API 封装 */

let _tauriDetected: boolean | null = null;

export const isTauri = (): boolean => {
  if (typeof window === 'undefined') return false;
  if (_tauriDetected !== null) return _tauriDetected;

  // Tauri 2.0 在 window 上挂载 __TAURI_INTERNALS__
  if (
    typeof window !== 'undefined' &&
    ('__TAURI_INTERNALS__' in window || '__TAURI__' in window)
  ) {
    _tauriDetected = true;
    return true;
  }

  // 兜底：Tauri 默认加载的页面 protocol 为 https://tauri.localhost/
  if (
    typeof window !== 'undefined' &&
    window.location &&
    window.location.hostname === 'tauri.localhost'
  ) {
    _tauriDetected = true;
    return true;
  }

  _tauriDetected = false;
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
      console.error('Tauri fs read failed:', e);
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
