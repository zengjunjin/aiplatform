use tauri::AppHandle;

pub async fn check_for_update(_app: &AppHandle) -> Result<bool, String> {
    // 使用 tauri_plugin_updater 检查更新
    // 注意：updater 插件已在 H18 注册
    // 这里提供命令供前端调用，实际更新检查在前端 useUpdater hook 中完成
    Ok(false)
}

#[tauri::command]
pub async fn manual_check_update(app: AppHandle) -> Result<bool, String> {
    check_for_update(&app).await
}
