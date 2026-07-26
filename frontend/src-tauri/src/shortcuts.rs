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
