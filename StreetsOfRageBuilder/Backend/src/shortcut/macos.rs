//! macOS: two `.app` bundles in a `StreetsOfRageProject` folder, in Applications or on the desktop.
//! The game's holds a copy of everything it needs, and the Launcher opens the `play.py` inside it.

use std::path::{Path, PathBuf};

use super::{entries, Inputs, GAME, LAUNCHER};
use crate::{dependencies, system};

pub const EXTENSION: &str = "app";
/// Where the step can put the folder, the first one found being what it shows on coming back.
pub const LOCATIONS: &[Option<&str>] = &[Some("applications"), Some("desktop")];
const ICON_ICNS: &[u8] = include_bytes!("../../icons/icon.icns");

pub fn desktop() -> Result<PathBuf, String> {
    let home = std::env::var_os("HOME").ok_or("cannot find the desktop folder")?;
    Ok(PathBuf::from(home).join("Desktop"))
}

/// The folder holding the two bundles.
pub fn destination(location: Option<&str>, desktop: &Path) -> PathBuf {
    let parent = if location == Some("desktop") { desktop } else { Path::new("/Applications") };
    parent.join("StreetsOfRageProject")
}

pub fn create(folder: &Path, _data: &Path, inputs: &Inputs) -> Result<(), String> {
    let (python, _) = dependencies::tk_python().ok_or("Python with Tk was not found; finish step 1 first")?;
    write_bundles(folder, inputs, &python)
}

fn sh_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

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
fn write_bundle(bundle: &Path, name: &str, identifier: &str, script: &str) -> Result<(), String> {
    let io = |e: std::io::Error| format!("cannot write {}: {e}", bundle.display());
    std::fs::create_dir_all(bundle.join("Contents/MacOS")).map_err(io)?;
    std::fs::create_dir_all(bundle.join("Contents/Resources")).map_err(io)?;
    std::fs::write(bundle.join("Contents/Info.plist"), info_plist(name, identifier)).map_err(io)?;
    std::fs::write(bundle.join("Contents/Resources/icon.icns"), ICON_ICNS).map_err(io)?;
    write_executable(&bundle.join("Contents/MacOS/launcher"), script)
}

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
const GAME_SCRIPT: &str = r#"#!/bin/sh
here=$(cd "$(dirname "$0")" && pwd)
resources="$here/../Resources"
rom="$resources/StreetsOfRageRecompilation/rom"
cd "$resources" || exit 1
exec "$here/sor" --rom "$rom/SOR.bin" --soundtrack "$rom/soundtrack" --ai-path "$resources/autoplay/ai-code" "$@"
"#;

/// Opens the `play.py` of the bundle next to it, with the Python that has Tk (the absolute path,
/// since a Finder launch has no Homebrew on `PATH`).
fn launcher_script(python: &Path) -> String {
    format!(
        "#!/bin/sh\ncd \"$(dirname \"$0\")/../../../{GAME}.app/Contents/Resources\" || exit 1\nexec {} scripts/play.py\n",
        sh_quote(&python.to_string_lossy()),
    )
}

/// Copy a folder, leaving out the files in `skip`.
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

fn copy_file(from: &Path, to: &Path) -> Result<(), String> {
    if let Some(parent) = to.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("cannot create {}: {e}", parent.display()))?;
    }
    std::fs::copy(from, to).map_err(|e| format!("cannot copy {}: {e}", from.display()))?;
    Ok(())
}

/// The libraries `otool -L` lists; the first line is the file itself. A library's own id comes back
/// too: the caller recognises it because it resolves to the library.
fn parse_libraries(otool: &str) -> Vec<String> {
    otool.lines().skip(1).filter_map(|line| line.trim().rsplit_once(" (compatibility").map(|(name, _)| name.to_owned())).collect()
}

/// The `LC_RPATH` entries `otool -l` lists.
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

fn is_system_library(name: &str) -> bool {
    name.starts_with("/usr/lib/") || name.starts_with("/System/")
}

/// Run a developer tool on a bundle's file, reporting what it says on failure.
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
fn write_bundles(folder: &Path, inputs: &Inputs, python: &Path) -> Result<(), String> {
    let [game, launcher] = entries(folder, EXTENSION);
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quotes_for_the_shell() {
        assert_eq!(sh_quote("it's"), "'it'\\''s'");
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
}
