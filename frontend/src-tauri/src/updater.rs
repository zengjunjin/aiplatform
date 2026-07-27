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

#[cfg(test)]
mod tests {
    // check_for_update 与 manual_check_update 均依赖 AppHandle（需要 Tauri runtime），
    // 无法在纯单元测试中构造 AppHandle，因此此处不进行 invoke 级测试。
    // check_for_update 当前实现始终返回 Ok(false)，实际更新检查在前端 useUpdater hook 中完成。
    #[test]
    fn updater_module_compiles() {
        // 编译期占位测试，确保 #[cfg(test)] 配置下模块可正常编译。
        assert!(true);
    }
}
