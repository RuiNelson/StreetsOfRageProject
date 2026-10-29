//! Running external programs with a search path that survives a stale environment:
//! a GUI app on macOS does not see Homebrew, and on Windows a freshly installed tool
//! is not on the PATH this process started with.

use std::ffi::OsString;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::sync::RwLock;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

static SEARCH_PATH: RwLock<Option<OsString>> = RwLock::new(None);

#[cfg(windows)]
fn extra_directories() -> Vec<PathBuf> {
    // Machine and user PATH as stored in the registry, expanded.
    let script = "[Environment]::ExpandEnvironmentVariables([Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User'))";
    let mut command = Command::new("powershell");
    command.args(["-NoProfile", "-NonInteractive", "-Command", script]).stdin(Stdio::null());
    command.creation_flags(0x0800_0000);
    command
        .output()
        .map(|out| std::env::split_paths(String::from_utf8_lossy(&out.stdout).trim()).collect())
        .unwrap_or_default()
}

#[cfg(target_os = "macos")]
fn extra_directories() -> Vec<PathBuf> {
    ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/local/sbin"]
        .map(PathBuf::from)
        .to_vec()
}

#[cfg(not(any(windows, target_os = "macos")))]
fn extra_directories() -> Vec<PathBuf> {
    ["/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin"].map(PathBuf::from).to_vec()
}

/// Recompute the search path; call before every round of checks or installs.
pub fn refresh_path() {
    let mut directories = extra_directories();
    if let Some(current) = std::env::var_os("PATH") {
        directories.extend(std::env::split_paths(&current));
    }
    let mut unique: Vec<PathBuf> = Vec::new();
    for directory in directories {
        if !directory.as_os_str().is_empty() && !unique.contains(&directory) {
            unique.push(directory);
        }
    }
    *SEARCH_PATH.write().unwrap() = std::env::join_paths(unique).ok();
}

fn search_path() -> OsString {
    if SEARCH_PATH.read().unwrap().is_none() {
        refresh_path();
    }
    SEARCH_PATH.read().unwrap().clone().unwrap_or_default()
}

/// Find an executable on the search path.
pub fn find_program(name: &str) -> Option<PathBuf> {
    let extensions: &[&str] = if cfg!(windows) { &["exe", "cmd", "bat"] } else { &[""] };
    std::env::split_paths(&search_path()).find_map(|directory| {
        extensions.iter().find_map(|extension| {
            let candidate = if extension.is_empty() {
                directory.join(name)
            } else {
                directory.join(format!("{name}.{extension}"))
            };
            candidate.is_file().then_some(candidate)
        })
    })
}

pub fn command(program: &Path) -> Command {
    let mut command = Command::new(program);
    command.env("PATH", search_path()).stdin(Stdio::null());
    #[cfg(windows)]
    command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    command
}

/// Run `name args...` and return its output; `None` when the program is missing or cannot start.
pub fn run(name: &str, args: &[&str]) -> Option<Output> {
    command(&find_program(name)?).args(args).output().ok()
}

/// First non-empty line of stdout (or stderr) of a successful run.
pub fn first_line(name: &str, args: &[&str]) -> Option<String> {
    let output = run(name, args)?;
    if !output.status.success() {
        return None;
    }
    [&output.stdout, &output.stderr]
        .into_iter()
        .flat_map(|bytes| String::from_utf8_lossy(bytes).lines().map(|l| l.trim().to_owned()).collect::<Vec<_>>())
        .find(|line| !line.is_empty())
}

/// Feed `on_line` every line of a child's output as it arrives; progress meters redraw with `\r`,
/// so that ends a line too. Empty lines are skipped.
pub fn read_lines(mut reader: impl Read, mut on_line: impl FnMut(String)) {
    let mut pending = Vec::new();
    let mut flush = |pending: &mut Vec<u8>| {
        let line = String::from_utf8_lossy(pending).trim().to_owned();
        pending.clear();
        if !line.is_empty() {
            on_line(line);
        }
    };
    let mut buffer = [0u8; 4096];
    loop {
        match reader.read(&mut buffer) {
            Ok(0) | Err(_) => break,
            Ok(count) => {
                for &byte in &buffer[..count] {
                    if byte == b'\r' || byte == b'\n' {
                        flush(&mut pending);
                    } else {
                        pending.push(byte);
                    }
                }
            }
        }
    }
    flush(&mut pending);
}
