mod dependencies;
mod platform;
mod system;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            platform::platform_info,
            dependencies::check_dependencies,
            dependencies::install_dependencies,
        ])
        .run(tauri::generate_context!())
        .expect("error while running the Streets of Rage Builder");
}
