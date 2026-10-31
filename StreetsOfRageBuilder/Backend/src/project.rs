//! Step 2: get the project onto disk with git, into the exact folder the user chose (so the
//! same folder is picked again to update it). It is always the commit tagged with this Builder's
//! version (user decision), neither older nor newer. Players only build and play, so the clone
//! carries a single commit of history, submodules included.

use std::path::Path;
use std::process::Stdio;

use serde::Serialize;
use tauri::ipc::Channel;

use crate::system;

const REPOSITORY: &str = "https://github.com/RuiNelson/StreetsOfRageProject.git";
/// The project's tag for this Builder: releases tag the commit they build, `0.3.1` with no `v`.
const TAG: &str = env!("CARGO_PKG_VERSION");
/// The origin of a copy of the project names this.
const PROJECT_NAME: &str = "StreetsOfRageProject";
/// Files a usable checkout has; a clone missing them is incomplete.
const EXPECTED: [&str; 2] = ["scripts/play.py", "StreetsOfRageRecompilation/CMakeLists.txt"];

#[derive(Serialize, Clone, Copy, PartialEq, Debug)]
#[serde(rename_all = "lowercase")]
pub enum State {
    /// The folder does not exist yet: it will be created and cloned into.
    Missing,
    /// An empty folder: it will be cloned into.
    Empty,
    /// The project is already there: it will be updated.
    Clone,
    /// Something else lives there: refuse.
    Occupied,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Inspection {
    pub path: String,
    pub state: State,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Downloaded {
    pub path: String,
    pub updated: bool,
    /// `abbreviated-hash (commit date)` of what is checked out.
    pub commit: String,
}

fn inspect(folder: &Path) -> Inspection {
    let state = if !folder.exists() {
        State::Missing
    } else if folder.join(".git").exists() {
        let origin = git_output(folder, &["remote", "get-url", "origin"]).unwrap_or_default();
        if origin.contains(PROJECT_NAME) { State::Clone } else { State::Occupied }
    } else if folder.read_dir().is_ok_and(|mut entries| entries.next().is_none()) {
        State::Empty
    } else {
        State::Occupied
    };
    Inspection { path: folder.to_string_lossy().into_owned(), state }
}

/// Run git with its progress streamed line by line (git redraws progress with `\r`).
fn git_stream(directory: Option<&Path>, args: &[&str], progress: &dyn Fn(String)) -> Result<(), String> {
    let git = system::find_program("git").ok_or("git was not found; finish step 1 first")?;
    let mut command = system::command(&git);
    command
        // Never wait for a username on a terminal the user cannot see.
        .env("GIT_TERMINAL_PROMPT", "0")
        .args(["-c", "core.longpaths=true"])
        .args(args)
        .stdout(Stdio::null())
        .stderr(Stdio::piped());
    if let Some(directory) = directory {
        command.current_dir(directory);
    }
    let mut child = command.spawn().map_err(|e| format!("could not start git: {e}"))?;
    let mut stderr = child.stderr.take().expect("stderr is piped");

    let mut lines: Vec<String> = Vec::new();
    system::read_lines(&mut stderr, |line| {
        progress(line.clone());
        lines.push(line);
    });

    let status = child.wait().map_err(|e| e.to_string())?;
    if status.success() {
        return Ok(());
    }
    let tail = lines.iter().rev().take(8).rev().cloned().collect::<Vec<_>>().join("\n");
    Err(format!("git {} failed ({status})\n{tail}", args.first().unwrap_or(&"")))
}

fn git_output(directory: &Path, args: &[&str]) -> Result<String, String> {
    let git = system::find_program("git").ok_or("git was not found; finish step 1 first")?;
    let output = system::command(&git).current_dir(directory).args(args).output().map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_owned());
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

/// The object id git gives `spec` (`HEAD`, `HEAD:path`) in `directory`, or `None` without git or a repository.
pub fn revision(directory: &Path, spec: &str) -> Option<String> {
    git_output(directory, &["rev-parse", spec]).ok().filter(|id| !id.is_empty())
}

fn update_submodules(path: &Path, progress: &dyn Fn(String)) -> Result<(), String> {
    progress("Fetching submodules…".into());
    git_stream(Some(path), &["submodule", "sync", "--recursive"], progress)?;
    git_stream(
        Some(path),
        &["submodule", "update", "--init", "--recursive", "--force", "--depth", "1", "--jobs", "4", "--progress"],
        progress,
    )
}

/// `git ls-remote --exit-code` fails silently when the tag is missing, and with a message when it
/// cannot reach the repository, which the clone or fetch then reports.
fn check_tag(repository: &str, tag: &str) -> Result<(), String> {
    let reference = format!("refs/tags/{tag}");
    match git_output(&std::env::temp_dir(), &["ls-remote", "--exit-code", "--tags", repository, &reference]) {
        Err(error) if error.is_empty() => {
            Err(format!("The project has no version {tag} to download: this Builder's version has not been released."))
        }
        _ => Ok(()),
    }
}

fn download(folder: &Path, repository: &str, tag: &str, progress: &dyn Fn(String)) -> Result<Downloaded, String> {
    system::refresh_path();
    let state = inspect(folder).state;
    if state == State::Occupied {
        return Err(format!("{} is not empty and is not a copy of the project.", folder.display()));
    }
    check_tag(repository, tag)?;
    let updated = match state {
        State::Occupied => unreachable!("refused above"),
        State::Missing | State::Empty => {
            if let Some(parent) = folder.parent() {
                std::fs::create_dir_all(parent).map_err(|e| format!("cannot create {}: {e}", parent.display()))?;
            }
            progress(format!("Cloning version {tag} of the project…"));
            let target = folder.to_string_lossy().into_owned();
            git_stream(
                None,
                &[
                    "clone", "--progress", "--depth", "1", "--branch", tag,
                    "--recurse-submodules", "--shallow-submodules", "--jobs", "4",
                    repository, &target,
                ],
                progress,
            )?;
            false
        }
        State::Clone => {
            progress(format!("Updating the project to version {tag}…"));
            let reference = format!("refs/tags/{tag}");
            let refspec = format!("+{reference}:{reference}");
            git_stream(Some(folder), &["fetch", "--progress", "--depth", "1", "origin", &refspec], progress)?;
            // Players do not edit the project: the update replaces local changes.
            git_stream(Some(folder), &["checkout", "--force", "--detach", &reference], progress)?;
            update_submodules(folder, progress)?;
            true
        }
    };
    if let Some(missing) = EXPECTED.iter().find(|file| !folder.join(file).is_file()) {
        return Err(format!("The download is incomplete: {missing} is missing."));
    }
    let commit = git_output(folder, &["log", "-1", "--format=%h (%cs)"])?;
    Ok(Downloaded { path: folder.to_string_lossy().into_owned(), updated, commit })
}

/// Clone or update the real repository into `folder` (for the ignored end-to-end tests).
#[cfg(test)]
pub fn download_project_for_test(folder: &Path) -> String {
    download(folder, REPOSITORY, TAG, &|_| {}).unwrap().path
}

#[tauri::command]
pub fn inspect_project(folder: String) -> Inspection {
    inspect(Path::new(&folder))
}

/// Clone (or update) the project in `folder`, reporting git's progress lines.
#[tauri::command]
pub async fn download_project(folder: String, progress: Channel<String>) -> Result<Downloaded, String> {
    tauri::async_runtime::spawn_blocking(move || {
        download(Path::new(&folder), REPOSITORY, TAG, &|line| {
            let _ = progress.send(line);
        })
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use std::process::Command;

    fn git(directory: &Path, args: &[&str]) {
        let status = Command::new("git")
            .current_dir(directory)
            .args(["-c", "protocol.file.allow=always", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"])
            .args(args)
            .status()
            .unwrap();
        assert!(status.success(), "git {args:?}");
    }

    fn write(directory: &Path, file: &str, text: &str) {
        let path = directory.join(file);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, text).unwrap();
    }

    /// Clone a tag of a local repository with a submodule and several commits, then update to another.
    #[test]
    fn clones_a_tag_shallow_with_submodules_then_updates_to_another() {
        let root = std::env::temp_dir().join(format!("sor-builder-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let sub = root.join("sub");
        let source = root.join(PROJECT_NAME); // a path containing the project name, as the origin check wants
        for directory in [&sub, &source] {
            std::fs::create_dir_all(directory).unwrap();
            git(directory, &["init", "-q", "-b", "main"]);
        }
        write(&sub, "CMakeLists.txt", "one");
        git(&sub, &["add", "."]);
        git(&sub, &["commit", "-q", "-m", "one"]);
        write(&sub, "CMakeLists.txt", "two");
        git(&sub, &["commit", "-q", "-am", "two"]);

        git(&source, &["submodule", "add", "-q", &format!("file://{}", sub.to_str().unwrap()), "StreetsOfRageRecompilation"]);
        write(&source, "scripts/play.py", "v1");
        git(&source, &["add", "."]);
        git(&source, &["commit", "-q", "-m", "v1"]);
        write(&source, "scripts/play.py", "v2");
        git(&source, &["commit", "-q", "-am", "v2"]);
        git(&source, &["tag", "1.0.0"]);
        write(&source, "scripts/play.py", "after 1.0.0");
        git(&source, &["commit", "-q", "-am", "after 1.0.0"]);

        // The code under test spawns git itself: let it use the local submodule too.
        unsafe {
            std::env::set_var("GIT_CONFIG_COUNT", "1");
            std::env::set_var("GIT_CONFIG_KEY_0", "protocol.file.allow");
            std::env::set_var("GIT_CONFIG_VALUE_0", "always");
        }
        let folder = root.join("my games").join("Streets of Rage");
        // A plain path would be a local clone, which ignores --depth.
        let url = format!("file://{}", source.to_str().unwrap());
        let url = url.as_str();
        assert_eq!(inspect(&folder).state, State::Missing);

        let missing = download(&folder, url, "9.9.9", &|_| {}).err().unwrap();
        assert!(missing.contains("no version 9.9.9"), "{missing}");
        assert_eq!(inspect(&folder).state, State::Missing);

        let first = download(&folder, url, "1.0.0", &|_| {}).unwrap();
        assert!(!first.updated);
        let project = PathBuf::from(&first.path);
        // The tag's commit, not the newer tip of the branch.
        assert_eq!(std::fs::read_to_string(project.join("scripts/play.py")).unwrap(), "v2");
        assert_eq!(git_output(&project, &["rev-list", "--count", "HEAD"]).unwrap(), "1");
        assert_eq!(
            git_output(&project.join("StreetsOfRageRecompilation"), &["rev-list", "--count", "HEAD"]).unwrap(),
            "1"
        );
        assert_eq!(inspect(&folder).state, State::Clone);

        // A new tag, and the branch moves past it; a local edit must not survive the update.
        write(&source, "scripts/play.py", "v3");
        git(&source, &["commit", "-q", "-am", "v3"]);
        git(&source, &["tag", "2.0.0"]);
        write(&source, "scripts/play.py", "after 2.0.0");
        git(&source, &["commit", "-q", "-am", "after 2.0.0"]);
        write(&project, "scripts/play.py", "edited");
        let second = download(&folder, url, "2.0.0", &|_| {}).unwrap();
        assert!(second.updated);
        assert_eq!(std::fs::read_to_string(project.join("scripts/play.py")).unwrap(), "v3");

        // An older Builder takes the folder back to its own version.
        let third = download(&folder, url, "1.0.0", &|_| {}).unwrap();
        assert!(third.updated);
        assert_eq!(std::fs::read_to_string(project.join("scripts/play.py")).unwrap(), "v2");

        std::fs::remove_dir_all(&root).unwrap();
    }

    /// Network: the real repository. `cargo test -- --ignored real_project` (set SOR_TEST_FOLDER).
    #[test]
    #[ignore]
    fn downloads_the_real_project() {
        let folder = PathBuf::from(std::env::var("SOR_TEST_FOLDER").expect("SOR_TEST_FOLDER"));
        let first = download(&folder, REPOSITORY, "0.2.0", &|line| println!("{line}")).unwrap();
        println!("{} {}", first.updated, first.commit);
        let second = download(&folder, REPOSITORY, TAG, &|_| {}).unwrap();
        assert!(second.updated);
        let tagged = format!("refs/tags/{TAG}^{{commit}}");
        assert_eq!(git_output(&folder, &["rev-parse", "HEAD"]).unwrap(), git_output(&folder, &["rev-parse", &tagged]).unwrap());
    }

    #[test]
    fn refuses_a_folder_that_is_not_empty_nor_the_project() {
        let folder = std::env::temp_dir().join(format!("sor-builder-occupied-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&folder);
        std::fs::create_dir_all(&folder).unwrap();
        assert_eq!(inspect(&folder).state, State::Empty);
        write(&folder, "notes.txt", "mine");
        assert_eq!(inspect(&folder).state, State::Occupied);
        assert!(download(&folder, "unused", "main", &|_| {}).is_err());
        std::fs::remove_dir_all(&folder).unwrap();
    }
}
