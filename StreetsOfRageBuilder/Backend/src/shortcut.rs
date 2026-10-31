//! Step 6: how the player starts the game (user decisions). Two entries everywhere, the game itself
//! and a Launcher that opens the `scripts/play.py` window. On Windows and Linux they are a `.lnk` or
//! a `.desktop` file on the desktop, pointing into the project. On macOS they are two `.app` bundles
//! in a `StreetsOfRageProject` folder, in Applications or on the desktop: the game's holds a copy of
//! everything it needs, and the Launcher opens the `play.py` inside it. The icon is embedded in this
//! program, so it does not depend on files inside the project.

use std::path::{Path, PathBuf};

use serde::Serialize;
use tauri::{AppHandle, Manager};

use crate::compile;
#[cfg(not(windows))]
use crate::dependencies;
use crate::system;

const GAME: &str = "StreetsOfRageRecompilation";
const LAUNCHER: &str = "StreetsOfRageRecompilation Launcher";
#[allow(dead_code)]
const ICON_PNG: &[u8] = include_bytes!("../icons/icon.png");
#[allow(dead_code)]
const ICON_ICO: &[u8] = include_bytes!("../icons/icon.ico");
#[allow(dead_code)]
const ICON_ICNS: &[u8] = include_bytes!("../icons/icon.icns");

#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Shortcut {
    /// What the user will find, the game's first.
    pub paths: Vec<String>,
    /// macOS only: "applications" or "desktop".
    pub location: Option<String>,
}

/// The desktop folder (it may be redirected, for example to OneDrive on Windows).
fn desktop() -> Result<PathBuf, String> {
    #[cfg(windows)]
    {
        let output = system::run("powershell", &["-NoProfile", "-NonInteractive", "-Command", "[Environment]::GetFolderPath('Desktop')"])
            .ok_or("PowerShell was not found")?;
        let path = String::from_utf8_lossy(&output.stdout).trim().to_owned();
        if !path.is_empty() {
            return Ok(PathBuf::from(path));
        }
    }
    #[cfg(not(windows))]
    {
        #[cfg(target_os = "linux")]
        if let Some(output) = system::run("xdg-user-dir", &["DESKTOP"]) {
            let path = String::from_utf8_lossy(&output.stdout).trim().to_owned();
            if !path.is_empty() && Path::new(&path).is_dir() {
                return Ok(PathBuf::from(path));
            }
        }
        if let Some(home) = std::env::var_os("HOME") {
            return Ok(PathBuf::from(home).join("Desktop"));
        }
    }
    Err("cannot find the desktop folder".into())
}

/// The game and the Launcher in `folder`.
fn entries(folder: &Path) -> [PathBuf; 2] {
    let extension = if cfg!(windows) {
        "lnk"
    } else if cfg!(target_os = "macos") {
        "app"
    } else {
        "desktop"
    };
    [folder.join(format!("{GAME}.{extension}")), folder.join(format!("{LAUNCHER}.{extension}"))]
}

/// What the game needs from a finished project.
struct Inputs {
    root: PathBuf,
    sor: PathBuf,
    rom: PathBuf,
    soundtrack: PathBuf,
    ai: PathBuf,
    #[allow(dead_code)]
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
fn game_options(inputs: &Inputs) -> [(&'static str, &Path); 3] {
    [("--rom", &inputs.rom), ("--soundtrack", &inputs.soundtrack), ("--ai-path", &inputs.ai)]
}

/// Quote a value for the `Exec` key of a desktop entry.
#[allow(dead_code)]
fn exec_quote(value: &str) -> String {
    let mut quoted = String::from("\"");
    for c in value.chars() {
        if matches!(c, '"' | '`' | '$' | '\\') {
            quoted.push('\\');
        }
        quoted.push(c);
    }
    quoted.push('"');
    quoted.replace('%', "%%")
}

#[allow(dead_code)]
fn desktop_entry(name: &str, comment: &str, command: &[&Path], project: &Path, icon: &Path) -> String {
    let exec: Vec<String> = command.iter().map(|part| exec_quote(&part.to_string_lossy())).collect();
    format!(
        "[Desktop Entry]\nType=Application\nName={name}\nComment={comment}\nExec={}\nPath={}\nIcon={}\nTerminal=false\nCategories=Game;\n",
        exec.join(" "),
        project.display(),
        icon.display(),
    )
}

#[allow(dead_code)]
fn game_desktop_entry(inputs: &Inputs, icon: &Path) -> String {
    let mut command: Vec<&Path> = vec![&inputs.sor];
    for (option, value) in game_options(inputs) {
        command.push(Path::new(option));
        command.push(value);
    }
    desktop_entry(GAME, "Play Streets of Rage", &command, &inputs.root, icon)
}

fn sh_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

#[allow(dead_code)]
fn info_plist(name: &str, identifier: &str) -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>{name}</string>
    <key>CFBundleDisplayName</key><string>{name}</string>
    <key>CFBundleIdentifier</key><string>{identifier}</string>
    <key>CFBundleExecutable</key><string>launcher</string>
    <key>CFBundleIconFile</key><string>icon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
"#
    )
}

/// A bundle's skeleton: `Info.plist`, the icon and the `sh` script Finder starts.
#[allow(dead_code)]
fn write_bundle(bundle: &Path, name: &str, identifier: &str, script: &str) -> Result<(), String> {
    let io = |e: std::io::Error| format!("cannot write {}: {e}", bundle.display());
    std::fs::create_dir_all(bundle.join("Contents/MacOS")).map_err(io)?;
    std::fs::create_dir_all(bundle.join("Contents/Resources")).map_err(io)?;
    std::fs::write(bundle.join("Contents/Info.plist"), info_plist(name, identifier)).map_err(io)?;
    std::fs::write(bundle.join("Contents/Resources/icon.icns"), ICON_ICNS).map_err(io)?;
    write_executable(&bundle.join("Contents/MacOS/launcher"), script)
}

#[allow(dead_code)]
fn write_executable(file: &Path, script: &str) -> Result<(), String> {
    let io = |e: std::io::Error| format!("cannot write {}: {e}", file.display());
    if let Some(parent) = file.parent() {
        std::fs::create_dir_all(parent).map_err(io)?;
    }
    std::fs::write(file, script).map_err(io)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(file, std::fs::Permissions::from_mode(0o755)).map_err(io)?;
    }
    Ok(())
}

/// Where the project's files go inside `Contents/Resources`: the checkout's own layout, so
/// `scripts/_common.py` and the scripts find everything without knowing about the bundle.
#[allow(dead_code)]
const GAME_SCRIPT: &str = r#"#!/bin/sh
here=$(cd "$(dirname "$0")" && pwd)
resources="$here/../Resources"
rom="$resources/StreetsOfRageRecompilation/rom"
cd "$resources" || exit 1
exec "$here/sor" --rom "$rom/SOR.bin" --soundtrack "$rom/soundtrack" --ai-path "$resources/autoplay/ai-code" "$@"
"#;

/// Opens the `play.py` of the bundle next to it, with the Python that has Tk (the absolute path,
/// since a Finder launch has no Homebrew on `PATH`).
#[allow(dead_code)]
fn launcher_script(python: &Path) -> String {
    format!(
        "#!/bin/sh\ncd \"$(dirname \"$0\")/../../../{GAME}.app/Contents/Resources\" || exit 1\nexec {} scripts/play.py\n",
        sh_quote(&python.to_string_lossy()),
    )
}

/// Copy a folder, leaving out the files in `skip`.
#[allow(dead_code)]
fn copy_tree(from: &Path, to: &Path, skip: &[&str]) -> Result<(), String> {
    std::fs::create_dir_all(to).map_err(|e| format!("cannot create {}: {e}", to.display()))?;
    let entries = std::fs::read_dir(from).map_err(|e| format!("cannot read {}: {e}", from.display()))?;
    for entry in entries {
        let entry = entry.map_err(|e| e.to_string())?;
        let name = entry.file_name();
        if skip.iter().any(|s| name == *s) {
            continue;
        }
        let (source, target) = (entry.path(), to.join(&name));
        if source.is_dir() {
            copy_tree(&source, &target, skip)?;
        } else {
            copy_file(&source, &target)?;
        }
    }
    Ok(())
}

#[allow(dead_code)]
fn copy_file(from: &Path, to: &Path) -> Result<(), String> {
    if let Some(parent) = to.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("cannot create {}: {e}", parent.display()))?;
    }
    std::fs::copy(from, to).map_err(|e| format!("cannot copy {}: {e}", from.display()))?;
    Ok(())
}

/// The libraries `otool -L` lists; the first line is the file itself. A library's own id comes back
/// too: the caller recognises it because it resolves to the library.
#[allow(dead_code)]
fn parse_libraries(otool: &str) -> Vec<String> {
    otool.lines().skip(1).filter_map(|line| line.trim().rsplit_once(" (compatibility").map(|(name, _)| name.to_owned())).collect()
}

/// The `LC_RPATH` entries `otool -l` lists.
#[allow(dead_code)]
fn parse_rpaths(otool: &str) -> Vec<String> {
    let mut rpaths = Vec::new();
    let mut lines = otool.lines();
    while let Some(line) = lines.next() {
        if line.trim() == "cmd LC_RPATH" {
            let path = lines.by_ref().find_map(|l| l.trim().strip_prefix("path ").and_then(|p| p.rsplit_once(" (offset")));
            if let Some((path, _)) = path {
                rpaths.push(path.to_owned());
            }
        }
    }
    rpaths
}

#[allow(dead_code)]
fn is_system_library(name: &str) -> bool {
    name.starts_with("/usr/lib/") || name.starts_with("/System/")
}

/// Run a developer tool on a bundle's file, reporting what it says on failure.
#[allow(dead_code)]
fn tool(program: &str, args: &[&str], file: &Path) -> Result<String, String> {
    let path = system::find_program(program).ok_or_else(|| format!("{program} was not found; install the Xcode command line tools (step 1)"))?;
    let output = system::command(&path).args(args).arg(file).output().map_err(|e| format!("{program}: {e}"))?;
    if !output.status.success() {
        return Err(format!("{program} failed on {}: {}", file.display(), String::from_utf8_lossy(&output.stderr).trim()));
    }
    Ok(String::from_utf8_lossy(&output.stdout).into_owned())
}

/// Copy the non-system libraries `sor` loads, directly or not, into `frameworks`, and point `sor`
/// and them at those copies, so the bundle needs nothing from the build tree or Homebrew. The tools
/// break the signatures, which Apple Silicon requires, so everything is signed again (ad hoc).
#[allow(dead_code)]
fn bundle_libraries(sor: &Path, source: &Path, frameworks: &Path) -> Result<(), String> {
    use std::collections::HashMap;

    std::fs::create_dir_all(frameworks).map_err(|e| format!("cannot create {}: {e}", frameworks.display()))?;
    let exe_dir = source.parent().unwrap_or(Path::new("/"));
    let expand = |value: &str, loader_dir: &Path| {
        PathBuf::from(value.replace("@loader_path", &loader_dir.to_string_lossy()).replace("@executable_path", &exe_dir.to_string_lossy()))
    };
    // Original library -> its name in Frameworks; several names can lead to one file.
    let mut names: HashMap<PathBuf, String> = HashMap::new();
    // Each copied file, with the references to change in it.
    let mut images: Vec<(PathBuf, Vec<(String, String)>, Vec<String>)> = Vec::new();
    let mut queue: Vec<(PathBuf, PathBuf, Vec<String>)> = vec![(source.to_owned(), sor.to_owned(), Vec::new())];
    while let Some((original, copy, inherited)) = queue.pop() {
        let own_rpaths = parse_rpaths(&tool("otool", &["-l"], &original)?);
        let loader_dir = original.parent().unwrap_or(Path::new("/")).to_owned();
        // dyld also searches the rpaths of the images that led here.
        let mut rpaths: Vec<PathBuf> = own_rpaths.iter().map(|r| expand(r, &loader_dir)).collect();
        rpaths.extend(inherited.iter().map(PathBuf::from));
        let mut changes = Vec::new();
        for reference in parse_libraries(&tool("otool", &["-L"], &original)?) {
            if is_system_library(&reference) {
                continue;
            }
            let found = match reference.strip_prefix("@rpath/") {
                Some(rest) => rpaths.iter().map(|r| r.join(rest)).find(|p| p.exists()),
                None => Some(expand(&reference, &loader_dir)).filter(|p| p.exists()),
            };
            let found = found.ok_or_else(|| format!("cannot find {reference}, needed by {}", original.display()))?;
            let library = found.canonicalize().map_err(|e| format!("{}: {e}", found.display()))?;
            if library == original.canonicalize().map_err(|e| format!("{}: {e}", original.display()))? {
                continue; // the library's own id
            }
            let name = match names.get(&library) {
                Some(name) => name.clone(),
                None => {
                    let name = Path::new(&reference).file_name().unwrap_or_default().to_string_lossy().into_owned();
                    let target = frameworks.join(&name);
                    copy_file(&library, &target)?;
                    // Homebrew's are read-only.
                    #[cfg(unix)]
                    {
                        use std::os::unix::fs::PermissionsExt;
                        std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o755)).map_err(|e| e.to_string())?;
                    }
                    names.insert(library.clone(), name.clone());
                    let passed_on = rpaths.iter().map(|r| r.to_string_lossy().into_owned()).collect();
                    queue.push((library, target, passed_on));
                    name
                }
            };
            changes.push((reference, format!("@rpath/{name}")));
        }
        images.push((copy, changes, own_rpaths));
    }
    for (copy, changes, rpaths) in &images {
        let is_sor = copy == sor;
        let mut args: Vec<String> = Vec::new();
        for rpath in rpaths {
            args.extend(["-delete_rpath".into(), rpath.clone()]);
        }
        if is_sor {
            args.extend(["-add_rpath".into(), "@executable_path/../Frameworks".into()]);
        } else {
            let name = copy.file_name().unwrap_or_default().to_string_lossy();
            args.extend(["-id".into(), format!("@rpath/{name}")]);
        }
        for (from, to) in changes {
            args.extend(["-change".into(), from.clone(), to.clone()]);
        }
        let args: Vec<&str> = args.iter().map(String::as_str).collect();
        tool("install_name_tool", &args, copy)?;
        tool("codesign", &["--force", "--sign", "-"], copy)?;
    }
    Ok(())
}

/// The game's bundle: `sor` and its libraries, the stdlib of its Python, the ROM, the soundtrack,
/// the AI, the scripts and autoplay.
#[allow(dead_code)]
fn write_game_bundle(bundle: &Path, inputs: &Inputs) -> Result<(), String> {
    const CACHES: [&str; 4] = ["__pycache__", ".pytest_cache", ".git", ".DS_Store"];
    write_bundle(bundle, GAME, "com.ruinelson.streetsofrage.game", GAME_SCRIPT)?;
    let contents = bundle.join("Contents");
    let resources = contents.join("Resources");
    let sor = contents.join("MacOS/sor");
    copy_file(&inputs.sor, &sor)?;
    bundle_libraries(&sor, &inputs.sor, &contents.join("Frameworks"))?;

    // SDL_GetBasePath, where SoRPython looks for python/, is Resources in a bundle.
    let build = inputs.sor.parent().unwrap_or(Path::new("."));
    copy_tree(&build.join("python"), &resources.join("python"), &[".DS_Store"])?;
    let game = resources.join(GAME);
    copy_file(&inputs.rom, &game.join("rom/SOR.bin"))?;
    copy_tree(&inputs.soundtrack, &game.join("rom/soundtrack"), &CACHES)?;
    for folder in ["scripts", "autoplay", "MegaDriveEnvironment/python/src"] {
        copy_tree(&inputs.root.join(folder), &resources.join(folder), &CACHES)?;
    }
    // Where scripts/run.py looks for the game. A script and not a symlink: run through a link, `sor`
    // is outside the bundle for SDL_GetBasePath, and does not find python/.
    let linked = game.join("build/sor");
    write_executable(&linked, "#!/bin/sh\nexec \"$(dirname \"$0\")/../../../MacOS/sor\" \"$@\"\n")
}

/// Make the two bundles in `folder`. The game's is made aside, so a failure leaves the old one.
#[allow(dead_code)]
fn create_macos(folder: &Path, inputs: &Inputs, python: &Path) -> Result<(), String> {
    let [game, launcher] = entries(folder);
    let staging = folder.join(format!(".{GAME}.staging"));
    let io = |e: std::io::Error| format!("cannot write in {}: {e}", folder.display());
    std::fs::create_dir_all(folder).map_err(io)?;
    let _ = std::fs::remove_dir_all(&staging);
    if let Err(error) = write_game_bundle(&staging, inputs) {
        let _ = std::fs::remove_dir_all(&staging);
        return Err(error);
    }
    let _ = std::fs::remove_dir_all(&game);
    std::fs::rename(&staging, &game).map_err(io)?;
    let _ = std::fs::remove_dir_all(&launcher);
    write_bundle(&launcher, LAUNCHER, "com.ruinelson.streetsofrage.launcher", &launcher_script(python))
}

#[cfg(windows)]
fn write_lnk(file: &Path, target: &Path, arguments: &str, project: &Path, icon: &Path, description: &str) -> Result<(), String> {
    let script = "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:SOR_LNK); \
                  $s.TargetPath = $env:SOR_TARGET; $s.Arguments = $env:SOR_ARGS; $s.WorkingDirectory = $env:SOR_DIR; \
                  $s.IconLocation = $env:SOR_ICON; $s.Description = $env:SOR_DESCRIPTION; $s.Save()";
    let output = system::command(Path::new("powershell"))
        .args(["-NoProfile", "-NonInteractive", "-Command", script])
        .env("SOR_LNK", file)
        .env("SOR_TARGET", target)
        .env("SOR_ARGS", arguments)
        .env("SOR_DIR", project)
        .env("SOR_ICON", icon)
        .env("SOR_DESCRIPTION", description)
        .output()
        .map_err(|e| e.to_string())?;
    if output.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_owned())
    }
}

#[cfg(windows)]
fn create_windows(desktop: &Path, data: &Path, inputs: &Inputs) -> Result<(), String> {
    // pyw runs Python without a console window.
    let pyw = system::find_program("pyw").ok_or("Python's pyw launcher was not found; finish step 1 first")?;
    let icon = data.join("icon.ico");
    std::fs::write(&icon, ICON_ICO).map_err(|e| format!("cannot write {}: {e}", icon.display()))?;
    let [game, launcher] = entries(desktop);
    let options: Vec<String> = game_options(inputs).iter().map(|(option, value)| format!("{option} \"{}\"", value.display())).collect();
    write_lnk(&game, &inputs.sor, &options.join(" "), &inputs.root, &icon, "Play Streets of Rage")?;
    write_lnk(&launcher, &pyw, &format!("-3 \"{}\"", inputs.play.display()), &inputs.root, &icon, "Open the Streets of Rage launcher")
}

#[cfg(target_os = "linux")]
fn create_linux(desktop: &Path, data: &Path, inputs: &Inputs) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    let (python, _) = dependencies::tk_python().ok_or("Python with Tk was not found; finish step 1 first")?;
    let icon = data.join("icon.png");
    std::fs::write(&icon, ICON_PNG).map_err(|e| format!("cannot write {}: {e}", icon.display()))?;
    let [game, launcher] = entries(desktop);
    let launcher_entry = desktop_entry(LAUNCHER, "Open the Streets of Rage launcher", &[python.as_path(), inputs.play.as_path()], &inputs.root, &icon);
    for (file, entry) in [(&game, game_desktop_entry(inputs, &icon)), (&launcher, launcher_entry)] {
        std::fs::write(file, entry).map_err(|e| format!("cannot write {}: {e}", file.display()))?;
        std::fs::set_permissions(file, std::fs::Permissions::from_mode(0o755)).map_err(|e| e.to_string())?;
        // GNOME only runs a desktop file it trusts; other desktops ignore this.
        let _ = system::run("gio", &["set", &file.to_string_lossy(), "metadata::trusted", "true"]);
    }
    Ok(())
}

/// macOS: the folder holding the two bundles for "applications" or "desktop". Elsewhere: the desktop.
fn destination(location: Option<&str>, desktop: &Path) -> PathBuf {
    if cfg!(target_os = "macos") {
        let parent = if location == Some("desktop") { desktop } else { Path::new("/Applications") };
        parent.join("StreetsOfRageProject")
    } else {
        desktop.to_owned()
    }
}

fn create(folder: &Path, data: &Path, project: &Path) -> Result<[PathBuf; 2], String> {
    system::refresh_path();
    let inputs = inputs(project)?;
    std::fs::create_dir_all(folder).map_err(|e| format!("cannot create {}: {e}", folder.display()))?;
    std::fs::create_dir_all(data).map_err(|e| format!("cannot create {}: {e}", data.display()))?;
    #[cfg(windows)]
    create_windows(folder, data, &inputs)?;
    #[cfg(target_os = "macos")]
    {
        let (python, _) = dependencies::tk_python().ok_or("Python with Tk was not found; finish step 1 first")?;
        create_macos(folder, &inputs, &python)?;
    }
    #[cfg(target_os = "linux")]
    create_linux(folder, data, &inputs)?;
    let _ = data;
    Ok(entries(folder))
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
    let files = create(&destination(location, &desktop()?), &data, Path::new(&project))?;
    Ok(shortcut(&files, location.filter(|_| cfg!(target_os = "macos"))))
}

/// The entries already made, if any.
#[tauri::command]
pub fn shortcut_status() -> Option<Shortcut> {
    let desktop = desktop().ok()?;
    let locations: &[Option<&str>] = if cfg!(target_os = "macos") { &[Some("applications"), Some("desktop")] } else { &[None] };
    locations.iter().find_map(|location| {
        let files = entries(&destination(*location, &desktop));
        files.iter().all(|file| file.exists()).then(|| shortcut(&files, *location))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fake_inputs() -> Inputs {
        Inputs {
            root: "/a b".into(),
            sor: "/a b/build/sor".into(),
            rom: "/a b/rom/SOR.bin".into(),
            soundtrack: "/a b/rom/soundtrack".into(),
            ai: "/a b/autoplay/ai-code".into(),
            play: "/a b/scripts/play.py".into(),
        }
    }

    #[test]
    fn quotes_paths_with_spaces_and_specials() {
        assert_eq!(exec_quote("/Users/a b/\"x\"$"), "\"/Users/a b/\\\"x\\\"\\$\"");
        assert_eq!(sh_quote("it's"), "'it'\\''s'");
        let entry = desktop_entry(LAUNCHER, "x", &[Path::new("/usr/bin/python3"), Path::new("/a b/scripts/play.py")], Path::new("/a b"), Path::new("/i.png"));
        assert!(entry.contains("Exec=\"/usr/bin/python3\" \"/a b/scripts/play.py\"\n"));
        assert!(entry.contains("Path=/a b\n"));
    }

    #[test]
    fn the_game_entry_passes_the_rom_soundtrack_and_ai() {
        let entry = game_desktop_entry(&fake_inputs(), Path::new("/i.png"));
        assert!(entry.contains(
            "Exec=\"/a b/build/sor\" \"--rom\" \"/a b/rom/SOR.bin\" \"--soundtrack\" \"/a b/rom/soundtrack\" \"--ai-path\" \"/a b/autoplay/ai-code\"\n"
        ));
    }

    #[test]
    fn reads_what_otool_prints() {
        let libraries = "/x/libA.dylib:\n\t@rpath/libA.dylib (compatibility version 0.0.0, current version 0.0.0)\n\t/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 2200.27.0)\n";
        assert_eq!(parse_libraries(libraries), ["@rpath/libA.dylib", "/usr/lib/libc++.1.dylib"]);
        let commands = "Load command 12\n          cmd LC_RPATH\n      cmdsize 32\n         path @loader_path (offset 12)\nLoad command 13\n          cmd LC_RPATH\n      cmdsize 32\n         path /a b/c (offset 12)\n";
        assert_eq!(parse_rpaths(commands), ["@loader_path", "/a b/c"]);
        assert!(is_system_library("/System/Library/Frameworks/Metal.framework/Metal"));
        assert!(!is_system_library("/opt/homebrew/opt/sdl3/lib/libSDL3.0.dylib"));
    }

    #[test]
    fn the_scripts_find_the_game_and_the_other_bundle() {
        assert!(GAME_SCRIPT.contains("exec \"$here/sor\" --rom \"$rom/SOR.bin\" --soundtrack \"$rom/soundtrack\" --ai-path \"$resources/autoplay/ai-code\" \"$@\""));
        let launcher = launcher_script(Path::new("/opt/it's/python3"));
        assert!(launcher.contains("../../../StreetsOfRageRecompilation.app/Contents/Resources\""));
        assert!(launcher.contains("exec '/opt/it'\\''s/python3' scripts/play.py"));
    }

    #[test]
    fn a_bundle_has_what_macos_needs() {
        let root = std::env::temp_dir().join(format!("sor-builder-bundle-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let bundle = root.join("x.app");
        write_bundle(&bundle, LAUNCHER, "com.example.x", "#!/bin/sh\n").unwrap();
        let plist = std::fs::read_to_string(bundle.join("Contents/Info.plist")).unwrap();
        assert!(plist.contains("<string>StreetsOfRageRecompilation Launcher</string>"));
        assert!(bundle.join("Contents/Resources/icon.icns").metadata().unwrap().len() > 1000);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(bundle.join("Contents/MacOS/launcher").metadata().unwrap().permissions().mode() & 0o111, 0o111);
        }
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn copying_a_tree_skips_the_caches() {
        let root = std::env::temp_dir().join(format!("sor-builder-tree-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(root.join("from/sub/__pycache__")).unwrap();
        std::fs::write(root.join("from/sub/a.py"), "a").unwrap();
        std::fs::write(root.join("from/sub/__pycache__/a.pyc"), "b").unwrap();
        copy_tree(&root.join("from"), &root.join("to"), &["__pycache__"]).unwrap();
        assert!(root.join("to/sub/a.py").is_file());
        assert!(!root.join("to/sub/__pycache__").exists());
        std::fs::remove_dir_all(&root).unwrap();
    }

    /// Makes the real entries in a scratch folder: `SOR_TEST_FOLDER=project SOR_TEST_DESKTOP=dir cargo test real_shortcut -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn creates_the_real_shortcut() {
        let project = std::env::var("SOR_TEST_FOLDER").expect("SOR_TEST_FOLDER");
        let desktop = PathBuf::from(std::env::var("SOR_TEST_DESKTOP").expect("SOR_TEST_DESKTOP"));
        let files = create(&destination(Some("desktop"), &desktop), &desktop.join("data"), Path::new(&project)).unwrap();
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
