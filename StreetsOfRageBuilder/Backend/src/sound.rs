//! Step 4: render the soundtrack from the ROM with the project's own `scripts/render_soundtrack.py`
//! (it builds the renderer, then renders every track to FLAC under `rom/soundtrack/`).

use std::path::{Path, PathBuf};

use serde::Serialize;
use tauri::ipc::Channel;

use crate::script;

#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Soundtrack {
    pub folder: String,
    pub files: usize,
}

fn soundtrack_folder(project: &Path) -> PathBuf {
    project.join("StreetsOfRageRecompilation").join("rom").join("soundtrack")
}

/// The soundtrack in the project, when a finished render is there (`manifest.tsv` is written last).
fn status(project: &Path) -> Option<Soundtrack> {
    let folder = soundtrack_folder(project);
    if !folder.join("manifest.tsv").is_file() {
        return None;
    }
    let files = folder
        .read_dir()
        .ok()?
        .filter_map(Result::ok)
        .filter(|entry| entry.path().extension().is_some_and(|extension| extension == "flac"))
        .count();
    Some(Soundtrack { folder: folder.to_string_lossy().into_owned(), files })
}

/// The Nuked OPN2 chip models `render_soundtrack.py --chip` accepts.
const CHIPS: [&str; 2] = ["ym3438", "ym2612"];

fn extract(project: &Path, chip: &str, progress: &(dyn Fn(String) + Sync)) -> Result<Soundtrack, String> {
    if !CHIPS.contains(&chip) {
        return Err(format!("unknown chip {chip}"));
    }
    if !project.join("scripts").join("render_soundtrack.py").is_file() {
        return Err(format!("{} is not the project folder; redo step 2.", project.display()));
    }
    if !project.join("StreetsOfRageRecompilation").join("rom").join("SOR.bin").is_file() {
        return Err("The ROM is not in the project yet; redo step 3.".into());
    }
    script::run(project, "render_soundtrack.py", &["--chip", chip], progress)?;
    status(project).ok_or_else(|| "The renderer finished but produced no soundtrack.".into())
}

#[tauri::command]
pub fn soundtrack_status(project: String) -> Option<Soundtrack> {
    status(Path::new(&project))
}

/// Render the soundtrack (several minutes the first time: it builds the renderer), reporting its output lines.
#[tauri::command]
pub async fn extract_sound(project: String, chip: String, progress: Channel<String>) -> Result<Soundtrack, String> {
    tauri::async_runtime::spawn_blocking(move || {
        extract(Path::new(&project), &chip, &|line| {
            let _ = progress.send(line);
        })
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn status_needs_the_manifest() {
        let project = std::env::temp_dir().join(format!("sor-builder-sound-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&project);
        let folder = soundtrack_folder(&project);
        std::fs::create_dir_all(&folder).unwrap();
        std::fs::write(folder.join("music_81_fm.flac"), b"x").unwrap();
        assert!(status(&project).is_none());
        std::fs::write(folder.join("manifest.tsv"), b"").unwrap();
        assert_eq!(status(&project).unwrap().files, 1);
        std::fs::remove_dir_all(&project).unwrap();
    }

    /// Network and minutes of compiling: `SOR_TEST_FOLDER=dir SOR_TEST_ROM=SOR.bin cargo test real_soundtrack -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn extracts_the_real_soundtrack() {
        let folder = std::env::var("SOR_TEST_FOLDER").expect("SOR_TEST_FOLDER");
        let rom = std::env::var("SOR_TEST_ROM").expect("SOR_TEST_ROM");
        let project = crate::project::download_project_for_test(Path::new(&folder));
        let report = crate::rom::use_rom(rom, project.clone()).unwrap();
        assert_eq!(report.crc, "4052E845");
        let soundtrack = extract(Path::new(&project), "ym3438", &|line| println!("{line}")).unwrap();
        println!("{soundtrack:?}");
        assert!(soundtrack.files > 50);
    }

    #[test]
    fn refuses_a_folder_without_the_project_or_rom() {
        let project = std::env::temp_dir().join(format!("sor-builder-sound-empty-{}", std::process::id()));
        std::fs::create_dir_all(project.join("scripts")).unwrap();
        assert!(extract(&project, "ym3438", &|_| {}).is_err());
        std::fs::write(project.join("scripts/render_soundtrack.py"), "").unwrap();
        assert!(extract(&project, "ym3438", &|_| {}).unwrap_err().contains("step 3"));
        assert!(extract(&project, "sid", &|_| {}).unwrap_err().contains("unknown chip"));
        std::fs::remove_dir_all(&project).unwrap();
    }
}
