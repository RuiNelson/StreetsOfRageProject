mod compile;
mod dependencies;
mod platform;
mod project;
mod rom;
mod script;
mod shortcut;
mod sound;
mod stamp;
mod system;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            platform::platform_info,
            platform::finish,
            dependencies::check_dependencies,
            dependencies::install_dependencies,
            project::inspect_project,
            project::download_project,
            rom::use_rom,
            rom::installed_rom,
            sound::soundtrack_status,
            sound::extract_sound,
            compile::game_status,
            compile::build_game,
            shortcut::create_shortcut,
            shortcut::shortcut_status,
        ])
        .run(tauri::generate_context!())
        .expect("error while running the Streets of Rage Builder");
}
