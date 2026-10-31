//! Step 6: how the player starts the game (user decisions). Two entries everywhere, the game itself
//! and a Launcher that opens the `scripts/play.py` window, made by the module of each system. The
//! icons are embedded in this program, so they do not depend on files inside the project.

use std::path::{Path, PathBuf};

use serde::Serialize;
use tauri::{AppHandle, Manager};

use crate::compile;
use crate::system;

// Each module's code also compiles, and its tests run, in the tests of the other Unix.
#[cfg(any(target_os = "linux", all(test, unix)))]
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
mod linux;
#[cfg(any(target_os = "macos", all(test, unix)))]
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
mod macos;
#[cfg(windows)]
mod windows;

#[cfg(target_os = "linux")]
use linux as platform;
#[cfg(target_os = "macos")]
use macos as platform;
#[cfg(windows)]
use windows as platform;

const GAME: &str = "StreetsOfRageRecompilation";
const LAUNCHER: &str = "StreetsOfRageRecompilation Launcher";

#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Shortcut {
    /// What the user will find, the game's first.
    pub paths: Vec<String>,
    /// macOS only: "applications" or "home".
    pub location: Option<String>,
}

/// The game and the Launcher in `folder`.
fn entries(folder: &Path, extension: &str) -> [PathBuf; 2] {
    [folder.join(format!("{GAME}.{extension}")), folder.join(format!("{LAUNCHER}.{extension}"))]
}

/// What the game needs from a finished project.
struct Inputs {
    root: PathBuf,
    sor: PathBuf,
    rom: PathBuf,
    soundtrack: PathBuf,
    ai: PathBuf,
    #[cfg_attr(target_os = "macos", allow(dead_code))]
    play: PathBuf,
}

fn inputs(project: &Path) -> Result<Inputs, String> {
    let play = project.join("scripts").join("play.py");
    if !play.is_file() {
        return Err(format!("{} is not the project folder; redo step 2.", project.display()));
    }
    let rom_folder = project.join("StreetsOfRageRecompilation").join("rom");
    let rom = rom_folder.join("SOR.bin");
    if !rom.is_file() {
        return Err("The ROM is not in the project; finish step 3 first.".into());
    }
    let soundtrack = rom_folder.join("soundtrack");
    if !soundtrack.join("manifest.tsv").is_file() {
        return Err("The soundtrack is not rendered; finish step 4 first.".into());
    }
    let sor = compile::executable(project).ok_or("The game is not built; finish step 5 first.")?;
    let ai = project.join("autoplay").join("ai-code");
    Ok(Inputs { root: project.to_owned(), sor, rom, soundtrack, ai, play })
}

/// `sor`'s options for the ROM, the pre-rendered soundtrack and the AI of 1 PLAYER AI ASSIST.
#[cfg_attr(target_os = "macos", allow(dead_code))]
fn game_options(inputs: &Inputs) -> [(&'static str, &Path); 3] {
    [("--rom", &inputs.rom), ("--soundtrack", &inputs.soundtrack), ("--ai-path", &inputs.ai)]
}

fn create(folder: &Path, data: &Path, project: &Path) -> Result<[PathBuf; 2], String> {
    system::refresh_path();
    let inputs = inputs(project)?;
    std::fs::create_dir_all(folder).map_err(|e| format!("cannot create {}: {e}", folder.display()))?;
    std::fs::create_dir_all(data).map_err(|e| format!("cannot create {}: {e}", data.display()))?;
    platform::create(folder, data, &inputs)?;
    Ok(entries(folder, platform::EXTENSION))
}

fn shortcut(files: &[PathBuf; 2], location: Option<&str>) -> Shortcut {
    Shortcut {
        paths: files.iter().map(|file| file.to_string_lossy().into_owned()).collect(),
        location: location.map(str::to_owned),
    }
}

/// Copying the bundle takes a while, so this does not run on the window's thread.
#[tauri::command(async)]
pub fn create_shortcut(app: AppHandle, project: String, location: Option<String>) -> Result<Shortcut, String> {
    let data = app.path().app_local_data_dir().map_err(|e| e.to_string())?;
    let location = location.as_deref();
    let files = create(&platform::destination(location)?, &data, Path::new(&project))?;
    Ok(shortcut(&files, location.filter(|_| platform::LOCATIONS[0].is_some())))
}

/// The entries already made, if any.
#[tauri::command]
pub fn shortcut_status() -> Option<Shortcut> {
    platform::LOCATIONS.iter().find_map(|location| {
        let files = entries(&platform::destination(*location).ok()?, platform::EXTENSION);
        files.iter().all(|file| file.exists()).then(|| shortcut(&files, *location))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Makes the real entries in a scratch folder: `SOR_TEST_FOLDER=project SOR_TEST_DESKTOP=dir cargo test real_shortcut -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn creates_the_real_shortcut() {
        let project = std::env::var("SOR_TEST_FOLDER").expect("SOR_TEST_FOLDER");
        let desktop = PathBuf::from(std::env::var("SOR_TEST_DESKTOP").expect("SOR_TEST_DESKTOP"));
        let files = create(&desktop.join("StreetsOfRageProject"), &desktop.join("data"), Path::new(&project)).unwrap();
        for file in &files {
            println!("{}", file.display());
            assert!(file.exists());
        }
    }

    #[test]
    fn refuses_a_folder_without_play_py() {
        let project = std::env::temp_dir().join(format!("sor-builder-shortcut-{}", std::process::id()));
        std::fs::create_dir_all(&project).unwrap();
        assert!(create(&project.join("desktop"), &project.join("data"), &project).is_err());
        std::fs::remove_dir_all(&project).unwrap();
    }
}
