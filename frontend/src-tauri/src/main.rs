#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    rag_platform_desktop_lib::run()
}

#[cfg(test)]
mod tests {
    // main() 仅调用 rag_platform_desktop_lib::run()，后者依赖完整 Tauri runtime，
    // 无法在纯单元测试中执行，因此不进行 invoke 级测试。
    #[test]
    fn main_module_compiles() {
        // 编译期占位测试，确保 #[cfg(test)] 配置下二进制 crate 可正常编译。
        assert!(true);
    }
}
