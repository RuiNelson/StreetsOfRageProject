//! Step 5: generate the C++ from the ROM and compile the game with the project's own
//! `scripts/generate_cpp_and_build.py --release` (a player wants the optimized build).

use std::path::{Path, PathBuf};

use serde::Serialize;
use tauri::ipc::Channel;

use crate::script;

#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Game {
    pub executable: String,
}

fn executable(project: &Path) -> PathBuf {
    let name = if cfg!(windows) { "sor.exe" } else { "sor" };
    project.join("StreetsOfRageRecompilation").join("build").join(name)
}

fn status(project: &Path) -> Option<Game> {
    let path = executable(project);
    path.is_file().then(|| Game { executable: path.to_string_lossy().into_owned() })
}

fn compile(project: &Path, progress: &(dyn Fn(String) + Sync)) -> Result<Game, String> {
    if !project.join("StreetsOfRageRecompilation").join("rom").join("SOR.bin").is_file() {
        return Err("The ROM is not in the project yet; redo step 3.".into());
    }
    script::run(project, "generate_cpp_and_build.py", &["--release"], progress)?;
    status(project).ok_or_else(|| format!("The build finished but {} was not produced.", executable(project).display()))
}

/// The game already built in the project, if any.
#[tauri::command]
pub fn game_status(project: String) -> Option<Game> {
    status(Path::new(&project))
}

/// Generate and compile the game (many minutes the first time), reporting the build output lines.
#[tauri::command]
pub async fn build_game(project: String, progress: Channel<String>) -> Result<Game, String> {
    tauri::async_runtime::spawn_blocking(move || {
        compile(Path::new(&project), &|line| {
            let _ = progress.send(line);
        })
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Network and many minutes of compiling: `SOR_TEST_FOLDER=dir SOR_TEST_ROM=SOR.bin cargo test real_game -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn builds_the_real_game() {
        let folder = std::env::var("SOR_TEST_FOLDER").expect("SOR_TEST_FOLDER");
        let rom = std::env::var("SOR_TEST_ROM").expect("SOR_TEST_ROM");
        let project = crate::project::download_project_for_test(Path::new(&folder));
        crate::rom::use_rom(rom, project.clone()).unwrap();
        let started = std::time::Instant::now();
        let game = compile(Path::new(&project), &|line| println!("{:>5}s {line}", started.elapsed().as_secs())).unwrap();
        println!("{game:?}");
    }

    #[test]
    fn status_needs_the_executable_and_the_build_needs_the_rom() {
        let project = std::env::temp_dir().join(format!("sor-builder-compile-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&project);
        std::fs::create_dir_all(project.join("StreetsOfRageRecompilation/build")).unwrap();
        assert!(status(&project).is_none());
        assert!(compile(&project, &|_| {}).unwrap_err().contains("step 3"));
        std::fs::write(executable(&project), b"").unwrap();
        assert!(status(&project).is_some());
        std::fs::remove_dir_all(&project).unwrap();
    }
}
