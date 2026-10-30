//! Step 5: generate the C++ from the ROM and compile the game with the project's own
//! `scripts/generate_cpp_and_build.py --release` (a player wants the optimized build).

use std::path::{Path, PathBuf};

use serde::Serialize;
use tauri::ipc::Channel;

use crate::{project, script, stamp};

#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Game {
    pub executable: String,
    /// Built from another version of the project than the one on disk now.
    pub outdated: bool,
}

fn build_folder(project: &Path) -> PathBuf {
    project.join("StreetsOfRageRecompilation").join("build")
}

/// The game is generated from the whole project, submodules included: its commit names them all.
fn version(project: &Path) -> Option<String> {
    project::revision(project, "HEAD")
}

/// Where the build put `sor`: single-configuration generators (Makefiles, Ninja) use the build
/// folder itself, multi-configuration ones (Visual Studio, Xcode) a folder per configuration.
/// The newest wins, as in the scripts' `built_executable`.
fn executable(project: &Path) -> Option<PathBuf> {
    let name = if cfg!(windows) { "sor.exe" } else { "sor" };
    let build = build_folder(project);
    ["", "Release", "RelWithDebInfo", "MinSizeRel", "Debug"]
        .iter()
        .map(|folder| build.join(folder).join(name))
        .filter(|path| path.is_file())
        .max_by_key(|path| path.metadata().and_then(|m| m.modified()).ok())
}

fn status(project: &Path) -> Option<Game> {
    executable(project).map(|path| Game {
        executable: path.to_string_lossy().into_owned(),
        outdated: !stamp::is_current(&build_folder(project), version(project)),
    })
}

fn compile(project: &Path, progress: &(dyn Fn(String) + Sync)) -> Result<Game, String> {
    if !project.join("StreetsOfRageRecompilation").join("rom").join("SOR.bin").is_file() {
        return Err("The ROM is not in the project yet; redo step 3.".into());
    }
    let built_from = version(project);
    script::run(project, "generate_cpp_and_build.py", &["--release"], progress)?;
    stamp::write(&build_folder(project), built_from);
    status(project).ok_or_else(|| "The build finished but the game (sor) was not found in its build folder.".to_string())
}

/// The game already built in the project, if any (`outdated` when the project was updated since).
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
        let build = project.join("StreetsOfRageRecompilation/build");
        std::fs::create_dir_all(&build).unwrap();
        let name = if cfg!(windows) { "sor.exe" } else { "sor" };
        assert!(status(&project).is_none());
        assert!(compile(&project, &|_| {}).unwrap_err().contains("step 3"));
        std::fs::write(build.join(name), b"").unwrap();
        assert!(status(&project).unwrap().executable.ends_with(name));
        std::fs::remove_dir_all(&project).unwrap();
    }

    /// A build made before the project moved on (or before stamps existed) is out of date.
    #[test]
    fn a_build_of_an_older_commit_is_outdated() {
        let project = std::env::temp_dir().join(format!("sor-builder-outdated-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&project);
        let build = project.join("StreetsOfRageRecompilation/build");
        std::fs::create_dir_all(&build).unwrap();
        let name = if cfg!(windows) { "sor.exe" } else { "sor" };
        std::fs::write(build.join(name), b"").unwrap();
        let git = |args: &[&str]| {
            let ok = std::process::Command::new("git")
                .current_dir(&project)
                .args(["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"])
                .args(args)
                .status()
                .unwrap()
                .success();
            assert!(ok, "git {args:?}");
        };
        git(&["init", "-q", "-b", "main"]);
        git(&["commit", "-q", "--allow-empty", "-m", "one"]);
        assert!(status(&project).unwrap().outdated, "no stamp");
        stamp::write(&build, version(&project));
        assert!(!status(&project).unwrap().outdated);
        git(&["commit", "-q", "--allow-empty", "-m", "two"]);
        assert!(status(&project).unwrap().outdated, "project moved on");
        std::fs::remove_dir_all(&project).unwrap();
    }

    /// Visual Studio and Xcode put the executable in a folder named after the configuration.
    #[test]
    fn finds_the_executable_of_a_multi_configuration_build() {
        let project = std::env::temp_dir().join(format!("sor-builder-multiconfig-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&project);
        let release = project.join("StreetsOfRageRecompilation/build/Release");
        std::fs::create_dir_all(&release).unwrap();
        let name = if cfg!(windows) { "sor.exe" } else { "sor" };
        std::fs::write(release.join(name), b"").unwrap();
        let found = status(&project).unwrap().executable;
        assert!(found.contains("Release"), "{found}");
        std::fs::remove_dir_all(&project).unwrap();
    }
}
