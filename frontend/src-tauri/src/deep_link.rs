use tauri::{AppHandle, Emitter};
use tauri_plugin_deep_link::DeepLinkExt;
use serde::Serialize;

#[derive(Serialize, Clone)]
pub struct DeepLinkPayload {
    pub route: String,
    pub id: Option<String>,
}

pub fn setup_deep_link(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let app_handle = app.clone();
    app.deep_link().on_open_url(move |event| {
        if let Some(url) = event.urls().first() {
            let parsed = parse_deep_link(&url.to_string());
            if let Some(payload) = parsed {
                let _ = app_handle.emit_to("main", "deep-link", payload);
            }
        }
    });
    Ok(())
}

fn parse_deep_link(url: &str) -> Option<DeepLinkPayload> {
    // 期望格式: rag-platform://kb/1, rag-platform://chat/abc, rag-platform://login
    let stripped = url.strip_prefix("rag-platform://")?;
    let parts: Vec<&str> = stripped.split('/').filter(|s| !s.is_empty()).collect();

    if parts.is_empty() {
        return None;
    }

    let route = parts[0].to_string();

    // 白名单路由校验
    let valid_routes = ["kb", "chat", "login", "settings"];
    if !valid_routes.contains(&route.as_str()) {
        return None;
    }

    // ID 校验：kb 和 chat 需要 ID，login 和 settings 不需要
    let id = if route == "kb" || route == "chat" {
        if parts.len() < 2 {
            return None;
        }
        let id_str = parts[1].to_string();
        if id_str.is_empty() {
            return None;
        }
        Some(id_str)
    } else {
        None
    };

    Some(DeepLinkPayload { route, id })
}
