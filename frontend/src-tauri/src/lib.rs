mod commands;
mod tray;
mod deep_link;
mod shortcuts;
mod updater;

use tauri::WindowEvent;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            commands::minimize_window,
            commands::toggle_maximize,
            commands::close_window,
            commands::set_focused,
            updater::manual_check_update,
        ])
        .setup(|app| {
            tray::create_tray(app)?;
            deep_link::setup_deep_link(app.handle())?;
            // 注册全局快捷键，失败时降级不阻塞启动
            let _ = shortcuts::register_shortcuts(app.handle());
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    let _ = window.hide();
                    api.prevent_close();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
