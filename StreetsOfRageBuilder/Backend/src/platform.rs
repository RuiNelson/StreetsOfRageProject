use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PlatformInfo {
    platform: &'static str,
    package_manager: Option<&'static str>,
}

/// The package manager each platform installs dependencies with.
const fn manager() -> (&'static str, &'static str) {
    if cfg!(target_os = "windows") {
        ("windows", "winget")
    } else if cfg!(target_os = "macos") {
        ("macos", "brew")
    } else {
        ("linux", "apt")
    }
}

fn on_path(program: &str) -> bool {
    std::env::var_os("PATH")
        .is_some_and(|paths| std::env::split_paths(&paths).any(|dir| {
            dir.join(program).is_file() || dir.join(format!("{program}.exe")).is_file()
        }))
}

#[tauri::command]
pub fn platform_info() -> PlatformInfo {
    let (platform, program) = manager();
    PlatformInfo { platform, package_manager: on_path(program).then_some(program) }
}
