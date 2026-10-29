mod platform;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![platform::platform_info])
        .run(tauri::generate_context!())
        .expect("error while running the Streets of Rage Builder");
}
