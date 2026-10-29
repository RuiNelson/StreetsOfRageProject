use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PlatformInfo {
    platform: &'static str,
    package_manager: &'static str,
}

/// The last step's Finish: end the wizard.
#[tauri::command]
pub fn finish(app: tauri::AppHandle) {
    app.exit(0);
}

#[tauri::command]
pub fn platform_info() -> PlatformInfo {
    if cfg!(target_os = "windows") {
        PlatformInfo { platform: "windows", package_manager: "winget" }
    } else if cfg!(target_os = "macos") {
        PlatformInfo { platform: "macos", package_manager: "brew" }
    } else {
        PlatformInfo { platform: "linux", package_manager: "apt" }
    }
}
