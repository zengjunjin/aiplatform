use tauri::Window;

#[tauri::command]
pub async fn minimize_window(window: Window) -> Result<(), String> {
    window.minimize().map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn toggle_maximize(window: Window) -> Result<(), String> {
    if window.is_maximized().map_err(|e| e.to_string())? {
        window.unmaximize().map_err(|e| e.to_string())
    } else {
        window.maximize().map_err(|e| e.to_string())
    }
}

#[tauri::command]
pub async fn close_window(window: Window) -> Result<(), String> {
    window.close().map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn set_focused(window: Window) -> Result<(), String> {
    window.set_focus().map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    // 所有命令函数（minimize_window / toggle_maximize / close_window / set_focused）
    // 均为 #[tauri::command] 且需要 Window 参数（依赖 Tauri runtime），
    // 无法在纯单元测试中构造 Window，因此不进行 invoke 级测试。
    #[test]
    fn commands_module_compiles() {
        // 编译期占位测试，确保 #[cfg(test)] 配置下模块可正常编译。
        assert!(true);
    }
}
