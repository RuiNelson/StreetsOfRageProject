//! Step 1: which build tools are present, and installing the missing ones with the
//! platform's package manager (winget, Homebrew or apt).

use std::path::PathBuf;

use serde::Serialize;

use crate::system::{self, find_program, first_line, refresh_path};

const WINGET_URL: &str = "https://winget.run";
const HOMEBREW_URL: &str = "https://github.com/Homebrew/brew/releases/";

/// The Debian/Ubuntu packages SDL3 needs to build from source (README, "Build on Ubuntu").
const SDL_LIBRARIES: &[&str] = &[
    "libasound2-dev", "libpulse-dev", "libx11-dev", "libxext-dev", "libxrandr-dev", "libxcursor-dev",
    "libxfixes-dev", "libxi-dev", "libxss-dev", "libxkbcommon-dev", "libdrm-dev", "libgbm-dev",
    "libgl1-mesa-dev", "libegl1-mesa-dev", "libdbus-1-dev", "libudev-dev", "libwayland-dev", "libdecor-0-dev",
];

#[derive(Serialize, Clone, Copy, PartialEq)]
#[serde(rename_all = "lowercase")]
enum State {
    Ok,
    Missing,
    /// Cannot be checked on this system.
    Unknown,
}

type Check = (State, Option<String>);

#[allow(dead_code)] // each platform builds only its own variants
enum Install {
    Winget { id: &'static str, over: Option<&'static str> },
    Brew(&'static [&'static str]),
    Apt(&'static [&'static str]),
    /// `xcode-select --install`: opens a system dialog and returns at once.
    XcodeTools,
}

struct Spec {
    id: &'static str,
    name: &'static str,
    description: &'static str,
    check: fn() -> Check,
    install: Install,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Dependency {
    id: &'static str,
    name: &'static str,
    description: &'static str,
    state: State,
    detail: Option<String>,
    installable: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Manager {
    name: &'static str,
    available: bool,
    /// Page the user must visit to install the manager.
    help_url: Option<&'static str>,
    /// Shown when the manager is missing.
    message: Option<String>,
    /// Linux without apt: the Debian package names to install by hand.
    manual_packages: Vec<&'static str>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Report {
    manager: Manager,
    dependencies: Vec<Dependency>,
    ready: bool,
}

// ---------------------------------------------------------------------------------------------
// Checks

fn version_of(name: &str) -> Check {
    match first_line(name, &["--version"]) {
        Some(line) => (State::Ok, Some(line)),
        None => (State::Missing, None),
    }
}

fn check_git() -> Check {
    version_of("git")
}

fn check_ninja() -> Check {
    version_of("ninja")
}

fn check_cmake() -> Check {
    let Some(line) = first_line("cmake", &["--version"]) else {
        return (State::Missing, None);
    };
    let version: Vec<u32> = line
        .split_whitespace()
        .last()
        .unwrap_or("")
        .split(|c: char| !c.is_ascii_digit())
        .filter_map(|part| part.parse().ok())
        .take(2)
        .collect();
    if version.as_slice() >= &[3, 24][..] {
        (State::Ok, Some(line))
    } else {
        (State::Missing, Some(format!("{line} (3.24 or newer is required)")))
    }
}

/// Python interpreters to try, as (program, leading arguments).
fn python_candidates() -> Vec<(PathBuf, Vec<&'static str>)> {
    let names: &[(&str, &[&str])] = if cfg!(windows) {
        // `python`/`python3` on Windows may be the Microsoft Store stub.
        &[("py", &["-3"])]
    } else {
        &[("python3", &[]), ("python3.15", &[]), ("python3.14", &[]), ("python3.13", &[]), ("python3.12", &[]), ("python3.11", &[]), ("python", &[])]
    };
    names
        .iter()
        .filter_map(|(name, args)| find_program(name).map(|path| (path, args.to_vec())))
        .filter(|(path, _)| !path.to_string_lossy().contains("WindowsApps"))
        .collect()
}

fn check_python() -> Check {
    let mut found: Option<String> = None;
    for (program, leading) in python_candidates() {
        let run = |code: &str| {
            system::command(&program).args(&leading).args(["-c", code]).output().ok().filter(|o| o.status.success())
        };
        let Some(version) = run("import sys; print('Python %d.%d.%d' % sys.version_info[:3])") else {
            continue;
        };
        let version = String::from_utf8_lossy(&version.stdout).trim().to_owned();
        if run("import tkinter").is_some() {
            return (State::Ok, Some(format!("{version}, with Tk")));
        }
        found.get_or_insert(version);
    }
    match found {
        Some(version) => (State::Missing, Some(format!("{version} has no Tk (tkinter)"))),
        None => (State::Missing, None),
    }
}

fn dpkg_installed(package: &str) -> bool {
    system::run("dpkg-query", &["-W", "-f=${Status}", package])
        .is_some_and(|o| String::from_utf8_lossy(&o.stdout).contains("install ok installed"))
}

#[allow(dead_code)]
fn check_packages(packages: &[&str]) -> Check {
    if find_program("dpkg-query").is_none() {
        return (State::Unknown, Some("cannot be checked without dpkg".into()));
    }
    let missing: Vec<&str> = packages.iter().copied().filter(|p| !dpkg_installed(p)).collect();
    if missing.is_empty() {
        (State::Ok, None)
    } else {
        (State::Missing, Some(format!("missing: {}", missing.join(", "))))
    }
}

#[cfg(target_os = "windows")]
fn check_compiler() -> Check {
    let architecture = if cfg!(target_arch = "aarch64") { "aarch64" } else { "x86_64" };
    let name = format!("{architecture}-w64-mingw32-clang");
    // winget adds llvm-mingw to PATH for new shells only; its install folder is the fallback.
    let packages = std::env::var_os("LOCALAPPDATA")
        .map(|dir| PathBuf::from(dir).join("Microsoft/WinGet/Packages"))
        .and_then(|dir| std::fs::read_dir(dir).ok());
    let installed = packages.into_iter().flatten().flatten().any(|package| {
        package.file_name().to_string_lossy().starts_with("MartinStorsjo.LLVM-MinGW.UCRT")
            && std::fs::read_dir(package.path()).into_iter().flatten().flatten().any(|release| {
                release.path().join("bin").join(format!("{name}.exe")).is_file()
            })
    });
    match first_line(&name, &["--version"]) {
        Some(line) => (State::Ok, Some(line)),
        None if installed => (State::Ok, Some("llvm-mingw installed (open a new terminal to use it)".into())),
        None => (State::Missing, None),
    }
}

#[cfg(target_os = "macos")]
fn check_tools() -> Check {
    // `git` and `clang++` in /usr/bin are shims that pop up an install dialog: look first.
    match system::run("xcode-select", &["-p"]) {
        Some(o) if o.status.success() => (State::Ok, Some(String::from_utf8_lossy(&o.stdout).trim().to_owned())),
        _ => (State::Missing, None),
    }
}

#[cfg(target_os = "macos")]
fn check_git_mac() -> Check {
    if check_tools().0 == State::Ok { check_git() } else { (State::Missing, None) }
}

#[cfg(not(any(windows, target_os = "macos")))]
fn check_compiler() -> Check {
    match first_line("g++", &["--version"]) {
        Some(line) => (State::Ok, Some(line)),
        None => (State::Missing, None),
    }
}

#[cfg(not(any(windows, target_os = "macos")))]
fn check_pkg_config() -> Check {
    version_of("pkg-config")
}

#[cfg(not(any(windows, target_os = "macos")))]
fn check_sdl_libraries() -> Check {
    check_packages(SDL_LIBRARIES)
}

// ---------------------------------------------------------------------------------------------
// Platform tables

#[cfg(target_os = "windows")]
fn specs() -> Vec<Spec> {
    vec![
        Spec { id: "git", name: "Git", description: "Downloads the project and its submodules.", check: check_git,
               install: Install::Winget { id: "Git.Git", over: None } },
        Spec { id: "cmake", name: "CMake 3.24+", description: "Configures the build.", check: check_cmake,
               install: Install::Winget { id: "Kitware.CMake", over: None } },
        Spec { id: "python", name: "Python 3 with Tk", description: "Runs the generator, the soundtrack renderer and the launcher.",
               check: check_python, install: Install::Winget { id: "Python.Python.3.14", over: None } },
        Spec { id: "ninja", name: "Ninja", description: "Builds quickly.", check: check_ninja,
               install: Install::Winget { id: "Ninja-build.Ninja", over: None } },
        Spec { id: "compiler", name: "llvm-mingw (Clang)", description: "The C++ compiler. No Visual Studio needed.",
               check: check_compiler, install: Install::Winget { id: "MartinStorsjo.LLVM-MinGW.UCRT", over: None } },
    ]
}

#[cfg(target_os = "macos")]
fn specs() -> Vec<Spec> {
    vec![
        Spec { id: "tools", name: "Xcode Command Line Tools", description: "The C++ compiler.", check: check_tools,
               install: Install::XcodeTools },
        Spec { id: "git", name: "Git", description: "Downloads the project and its submodules (included in the Command Line Tools).",
               check: check_git_mac, install: Install::XcodeTools },
        Spec { id: "cmake", name: "CMake 3.24+", description: "Configures the build.", check: check_cmake,
               install: Install::Brew(&["cmake"]) },
        Spec { id: "ninja", name: "Ninja", description: "Builds quickly.", check: check_ninja,
               install: Install::Brew(&["ninja"]) },
        Spec { id: "python", name: "Python 3 with Tk", description: "Runs the generator, the soundtrack renderer and the launcher.",
               check: check_python, install: Install::Brew(&["python", "python-tk"]) },
    ]
}

#[cfg(not(any(windows, target_os = "macos")))]
fn specs() -> Vec<Spec> {
    vec![
        Spec { id: "git", name: "Git", description: "Downloads the project and its submodules.", check: check_git,
               install: Install::Apt(&["git"]) },
        Spec { id: "compiler", name: "C++ compiler and make", description: "build-essential.", check: check_compiler,
               install: Install::Apt(&["build-essential"]) },
        Spec { id: "cmake", name: "CMake 3.24+", description: "Configures the build.", check: check_cmake,
               install: Install::Apt(&["cmake"]) },
        Spec { id: "ninja", name: "Ninja", description: "Builds quickly.", check: check_ninja,
               install: Install::Apt(&["ninja-build"]) },
        Spec { id: "pkg-config", name: "pkg-config", description: "Locates system libraries.", check: check_pkg_config,
               install: Install::Apt(&["pkg-config"]) },
        Spec { id: "python", name: "Python 3 with Tk", description: "Runs the generator, the soundtrack renderer and the launcher.",
               check: check_python, install: Install::Apt(&["python3", "python3-tk"]) },
        Spec { id: "sdl-libraries", name: "SDL development libraries", description: "Audio, video and input headers SDL3 needs to build.",
               check: check_sdl_libraries, install: Install::Apt(SDL_LIBRARIES) },
    ]
}

/// Linux without apt: everything the user has to install by hand.
#[allow(dead_code)]
fn debian_package_names() -> Vec<&'static str> {
    let mut names = vec!["git", "build-essential", "cmake", "ninja-build", "pkg-config", "python3", "python3-tk"];
    names.extend_from_slice(SDL_LIBRARIES);
    names
}

fn manager() -> Manager {
    let (name, program, help_url, message) = if cfg!(windows) {
        ("winget", "winget", Some(WINGET_URL),
         "winget is not installed. Install it from the page below, then press Re-check.".to_owned())
    } else if cfg!(target_os = "macos") {
        ("Homebrew", "brew", Some(HOMEBREW_URL),
         "Homebrew is not installed. Install it from the page below, then press Re-check.".to_owned())
    } else {
        ("apt", "apt-get", None,
         "Sorry, only apt (Debian, Ubuntu and derivatives) is supported for now. Please install the packages below \
          with your distribution's package manager, then press Re-check.".to_owned())
    };
    let available = find_program(program).is_some();
    Manager {
        name,
        available,
        help_url: if available { None } else { help_url },
        message: if available { None } else { Some(message) },
        manual_packages: if cfg!(not(any(windows, target_os = "macos"))) && !available { debian_package_names() } else { vec![] },
    }
}

fn evaluate(spec: &Spec, manager_available: bool) -> Dependency {
    let (state, detail) = (spec.check)();
    Dependency {
        id: spec.id,
        name: spec.name,
        description: spec.description,
        state,
        detail,
        installable: state != State::Ok && manager_available,
    }
}

fn report() -> Report {
    refresh_path();
    let manager = manager();
    let dependencies: Vec<Dependency> = specs().iter().map(|spec| evaluate(spec, manager.available)).collect();
    let ready = dependencies.iter().all(|d| d.state == State::Ok);
    Report { manager, dependencies, ready }
}

// ---------------------------------------------------------------------------------------------
// Installing: the commands run in the system terminal, so the user sees the installers'
// own output and prompts (passwords, licence questions). We do not wait for them.

/// Shell-quote one word for sh.
#[cfg(not(windows))]
fn quote(word: &str) -> String {
    format!("'{}'", word.replace('\'', "'\\''"))
}

#[cfg(windows)]
fn install_line(spec: &Spec) -> Option<String> {
    let Install::Winget { id, over } = &spec.install else { return None };
    let over = over.map(|o| format!(" --override \"{o}\"")).unwrap_or_default();
    Some(format!(
        "winget install --exact --id {id} --source winget --accept-package-agreements --accept-source-agreements{over}"
    ))
}

#[cfg(target_os = "macos")]
fn install_line(spec: &Spec) -> Option<String> {
    match &spec.install {
        Install::Brew(formulas) => {
            let brew = find_program("brew")?;
            Some(format!("{} install {}", quote(&brew.to_string_lossy()), formulas.join(" ")))
        }
        _ => None,
    }
}

/// Everything apt needs, in one command so the password is asked once.
#[cfg(not(any(windows, target_os = "macos")))]
fn apt_line(requested: &[&Spec]) -> Option<String> {
    let mut packages: Vec<&str> = requested
        .iter()
        .filter_map(|s| if let Install::Apt(p) = &s.install { Some(p.iter().copied()) } else { None })
        .flatten()
        .collect();
    packages.dedup();
    let is_root = first_line("id", &["-u"]).as_deref() == Some("0");
    let sudo = if is_root { "" } else { "sudo " };
    (!packages.is_empty())
        .then(|| format!("{sudo}apt-get update && {sudo}apt-get install -y {}", packages.join(" ")))
}

#[cfg(not(any(windows, target_os = "macos")))]
fn terminal_lines(requested: &[&Spec]) -> Vec<String> {
    apt_line(requested).into_iter().collect()
}

#[cfg(any(windows, target_os = "macos"))]
fn terminal_lines(requested: &[&Spec]) -> Vec<String> {
    requested.iter().filter_map(|spec| install_line(spec)).collect()
}

#[cfg(windows)]
fn open_terminal(lines: &[String]) -> Result<(), String> {
    use std::os::windows::process::CommandExt;

    let mut script = String::from("@echo off\r\ntitle Streets of Rage Builder\r\n");
    for line in lines {
        script += &format!("echo.\r\necho ^> {}\r\n{line}\r\n", line.replace('"', "'").replace(['&', '|', '<', '>'], ""));
    }
    script += "echo.\r\necho Finished. Close this window and press Re-check in the app.\r\npause\r\n";
    let path = std::env::temp_dir().join("streets-of-rage-builder-install.bat");
    std::fs::write(&path, script).map_err(|e| e.to_string())?;
    let cmd = find_program("cmd").ok_or("cmd.exe not found")?;
    system::command(&cmd)
        .raw_arg(format!("/c start \"Streets of Rage Builder\" \"{}\"", path.display()))
        .spawn()
        .map(drop)
        .map_err(|e| e.to_string())
}

#[cfg(not(windows))]
fn write_script(lines: &[String], name: &str) -> Result<std::path::PathBuf, String> {
    use std::os::unix::fs::PermissionsExt;

    let mut script = String::from("#!/bin/sh\n");
    if let Some(path) = std::env::var_os("PATH") {
        script += &format!("PATH={}\nexport PATH\n", quote(&path.to_string_lossy()));
    }
    for line in lines {
        script += &format!("echo\necho {}\n{line}\n", quote(&format!("$ {line}")));
    }
    script += "echo\necho 'Finished. Close this window and press Re-check in the app.'\nprintf 'Press Enter to close...'\nread _\n";
    let path = std::env::temp_dir().join(name);
    std::fs::write(&path, script).map_err(|e| e.to_string())?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755)).map_err(|e| e.to_string())?;
    Ok(path)
}

#[cfg(target_os = "macos")]
fn open_terminal(lines: &[String]) -> Result<(), String> {
    let script = write_script(lines, "streets-of-rage-builder-install.command")?;
    let open = find_program("open").ok_or("open not found")?;
    system::command(&open).args(["-a", "Terminal"]).arg(script).spawn().map(drop).map_err(|e| e.to_string())
}

#[cfg(not(any(windows, target_os = "macos")))]
fn open_terminal(lines: &[String]) -> Result<(), String> {
    // (program, arguments that precede the command to run)
    const TERMINALS: &[(&str, &[&str])] = &[
        ("x-terminal-emulator", &["-e"]),
        ("gnome-terminal", &["--"]),
        ("konsole", &["-e"]),
        ("xfce4-terminal", &["-x"]),
        ("kitty", &[]),
        ("alacritty", &["-e"]),
        ("xterm", &["-e"]),
    ];
    let script = write_script(lines, "streets-of-rage-builder-install.sh")?;
    for (name, leading) in TERMINALS {
        if let Some(program) = find_program(name) {
            return system::command(&program).args(*leading).arg(&script).spawn().map(drop).map_err(|e| e.to_string());
        }
    }
    Err(format!("No terminal emulator found. Run this in a terminal instead:\n{}", lines.join("\n")))
}

fn install(requested: &[&Spec]) -> Result<Vec<String>, String> {
    let mut notes = Vec::new();
    if requested.iter().any(|s| matches!(s.install, Install::XcodeTools)) {
        // The Command Line Tools have their own system dialog.
        let _ = system::run("xcode-select", &["--install"]);
        notes.push("A system dialog opened to install the Command Line Tools. Finish it, then press Re-check.".to_owned());
    }
    let lines = terminal_lines(requested);
    if !lines.is_empty() {
        open_terminal(&lines)?;
        notes.push("A terminal window opened to run the installation. When it finishes, press Re-check.".to_owned());
    }
    Ok(notes)
}

// ---------------------------------------------------------------------------------------------
// Commands

#[tauri::command]
pub async fn check_dependencies() -> Result<Report, String> {
    tauri::async_runtime::spawn_blocking(report).await.map_err(|e| e.to_string())
}

/// Install the given dependencies together (one apt or brew call, one password prompt).
#[tauri::command]
pub async fn install_dependencies(ids: Vec<String>) -> Result<Vec<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        refresh_path();
        let all = specs();
        let requested: Vec<&Spec> = all.iter().filter(|s| ids.iter().any(|id| id == s.id)).collect();
        if requested.is_empty() {
            return Err("nothing to install".to_owned());
        }
        install(&requested)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn report_lists_every_spec_once() {
        let report = report();
        let ids: Vec<&str> = report.dependencies.iter().map(|d| d.id).collect();
        let mut unique = ids.clone();
        unique.sort();
        unique.dedup();
        assert_eq!(ids.len(), unique.len());
        assert!(!ids.is_empty());
        println!("{}", serde_json::to_string_pretty(&report).unwrap());
    }

    #[cfg(not(windows))]
    #[test]
    fn install_script_is_valid_sh() {
        let lines = vec!["echo 'it works'".to_owned(), "true".to_owned()];
        let script = write_script(&lines, "streets-of-rage-builder-test.sh").unwrap();
        let status = std::process::Command::new("sh").arg("-n").arg(&script).status().unwrap();
        assert!(status.success());
        let output = std::process::Command::new("sh").arg(&script).stdin(std::process::Stdio::null()).output().unwrap();
        assert!(String::from_utf8_lossy(&output.stdout).contains("it works"));
        let _ = std::fs::remove_file(script);
    }
}
