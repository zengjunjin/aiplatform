export interface TauriWindowState {
  isMinimized: boolean;
  isMaximized: boolean;
  isFocused: boolean;
}

export interface TauriWindowAPI {
  minimize: () => Promise<void>;
  toggleMaximize: () => Promise<void>;
  close: () => Promise<void>;
  setFocused: () => Promise<void>;
  isTauri: () => boolean;
}
