use tauri::{AppHandle, Emitter};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use serde::Serialize;

#[derive(Serialize, Clone)]
pub struct ShortcutPayload {
    pub action: String,
}

pub fn register_shortcuts(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let shortcuts = vec![
        (Code::KeyK, "open_search"),
        (Code::KeyN, "new_chat"),
        (Code::KeyD, "toggle_devtools"),
    ];

    for (key, action) in shortcuts {
        let shortcut = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), key);
        let app_handle = app.clone();
        let action_str = action.to_string();

        app.global_shortcut().on_shortcut(shortcut, move |_app, _shortcut, event| {
            if event.state() == ShortcutState::Pressed {
                let _ = app_handle.emit_to("main", "shortcut", ShortcutPayload {
                    action: action_str.clone(),
                });
            }
        })?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shortcut_payload_serializes_correctly() {
        let p = ShortcutPayload {
            action: "open_search".to_string(),
        };
        let json = serde_json::to_value(&p).unwrap();
        assert_eq!(json["action"], "open_search");
    }

    #[test]
    fn shortcut_payload_clone_is_equal() {
        let p = ShortcutPayload {
            action: "new_chat".to_string(),
        };
        let cloned = p.clone();
        assert_eq!(cloned.action, p.action);
    }

    #[test]
    fn shortcut_payload_serializes_all_known_actions() {
        // 与 register_shortcuts 中注册的 action 保持一致
        for action in ["open_search", "new_chat", "toggle_devtools"] {
            let p = ShortcutPayload {
                action: action.to_string(),
            };
            let json = serde_json::to_value(&p).unwrap();
            assert_eq!(json["action"], action);
        }
    }
}
