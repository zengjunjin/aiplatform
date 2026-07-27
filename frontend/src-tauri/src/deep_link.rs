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

#[cfg(test)]
mod tests {
    use super::*;

    // ---- parse_deep_link: 有效输入 ----

    #[test]
    fn parse_kb_with_id() {
        let p = parse_deep_link("rag-platform://kb/1").unwrap();
        assert_eq!(p.route, "kb");
        assert_eq!(p.id, Some("1".to_string()));
    }

    #[test]
    fn parse_chat_with_id() {
        let p = parse_deep_link("rag-platform://chat/abc").unwrap();
        assert_eq!(p.route, "chat");
        assert_eq!(p.id, Some("abc".to_string()));
    }

    #[test]
    fn parse_login_without_id() {
        let p = parse_deep_link("rag-platform://login").unwrap();
        assert_eq!(p.route, "login");
        assert_eq!(p.id, None);
    }

    #[test]
    fn parse_settings_without_id() {
        let p = parse_deep_link("rag-platform://settings").unwrap();
        assert_eq!(p.route, "settings");
        assert_eq!(p.id, None);
    }

    // ---- parse_deep_link: 边界与非法输入 ----

    #[test]
    fn parse_wrong_prefix_returns_none() {
        assert!(parse_deep_link("http://kb/1").is_none());
        assert!(parse_deep_link("rag-platform:/kb/1").is_none()); // 单斜杠
        assert!(parse_deep_link("rag-platformkb/1").is_none());
    }

    #[test]
    fn parse_empty_url_returns_none() {
        assert!(parse_deep_link("").is_none());
    }

    #[test]
    fn parse_only_scheme_returns_none() {
        assert!(parse_deep_link("rag-platform://").is_none());
    }

    #[test]
    fn parse_invalid_route_returns_none() {
        assert!(parse_deep_link("rag-platform://foo").is_none());
        assert!(parse_deep_link("rag-platform://foo/1").is_none());
        assert!(parse_deep_link("rag-platform://KB/1").is_none()); // 大小写敏感
    }

    #[test]
    fn parse_kb_without_id_returns_none() {
        assert!(parse_deep_link("rag-platform://kb").is_none());
    }

    #[test]
    fn parse_chat_without_id_returns_none() {
        assert!(parse_deep_link("rag-platform://chat").is_none());
    }

    #[test]
    fn parse_kb_empty_id_returns_none() {
        assert!(parse_deep_link("rag-platform://kb/").is_none());
    }

    #[test]
    fn parse_chat_empty_id_returns_none() {
        assert!(parse_deep_link("rag-platform://chat/").is_none());
    }

    #[test]
    fn parse_login_trailing_slash_ok() {
        // login 不需要 id，尾斜杠产生的空段被过滤
        let p = parse_deep_link("rag-platform://login/").unwrap();
        assert_eq!(p.route, "login");
        assert_eq!(p.id, None);
    }

    #[test]
    fn parse_kb_extra_segments_uses_first_id() {
        // rag-platform://kb/1/2 → id 取第一段 "1"
        let p = parse_deep_link("rag-platform://kb/1/2").unwrap();
        assert_eq!(p.route, "kb");
        assert_eq!(p.id, Some("1".to_string()));
    }

    #[test]
    fn parse_kb_double_slash_returns_none() {
        // kb// → 过滤空段后只剩 ["kb"]，缺 id
        assert!(parse_deep_link("rag-platform://kb//").is_none());
    }

    #[test]
    fn parse_settings_and_login_pass_whitelist() {
        for route in ["login", "settings"] {
            let url = format!("rag-platform://{}", route);
            let p = parse_deep_link(&url).unwrap();
            assert_eq!(p.route, route);
            assert!(p.id.is_none());
        }
    }

    #[test]
    fn parse_kb_with_unicode_id() {
        let p = parse_deep_link("rag-platform://kb/知识库1").unwrap();
        assert_eq!(p.route, "kb");
        assert_eq!(p.id, Some("知识库1".to_string()));
    }

    // ---- DeepLinkPayload 序列化与 Clone ----

    #[test]
    fn payload_with_id_serializes_correctly() {
        let p = DeepLinkPayload {
            route: "kb".to_string(),
            id: Some("1".to_string()),
        };
        let json = serde_json::to_value(&p).unwrap();
        assert_eq!(json["route"], "kb");
        assert_eq!(json["id"], "1");
    }

    #[test]
    fn payload_with_none_id_serializes_to_null() {
        let p = DeepLinkPayload {
            route: "login".to_string(),
            id: None,
        };
        let json = serde_json::to_value(&p).unwrap();
        assert_eq!(json["route"], "login");
        assert!(json["id"].is_null());
    }

    #[test]
    fn payload_is_clone_and_equal() {
        let p = DeepLinkPayload {
            route: "chat".to_string(),
            id: Some("x".to_string()),
        };
        let cloned = p.clone();
        assert_eq!(cloned.route, p.route);
        assert_eq!(cloned.id, p.id);
    }
}
