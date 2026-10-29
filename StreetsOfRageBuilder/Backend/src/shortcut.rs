//! Step 6: a desktop shortcut that opens `scripts/play.py` (user decisions: the play.py window,
//! on the desktop, with the punch icon). Each platform gets its native kind: a `.lnk` on Windows,
//! an `.app` on macOS and a `.desktop` file on Linux. The icon is embedded in this program, so the
//! shortcut does not depend on files inside the project.

use std::path::{Path, PathBuf};

use serde::Serialize;
use tauri::{AppHandle, Manager};

use crate::{dependencies, system};

const NAME: &str = "Streets of Rage";
#[allow(dead_code)]
const ICON_PNG: &[u8] = include_bytes!("../icons/icon.png");
#[allow(dead_code)]
const ICON_ICO: &[u8] = include_bytes!("../icons/icon.ico");
#[allow(dead_code)]
const ICON_ICNS: &[u8] = include_bytes!("../icons/icon.icns");

#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Shortcut {
    /// What the user will see on the desktop.
    pub path: String,
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

fn shortcut_file(desktop: &Path) -> PathBuf {
    let file = if cfg!(windows) {
        format!("{NAME}.lnk")
    } else if cfg!(target_os = "macos") {
        format!("{NAME}.app")
    } else {
        format!("{NAME}.desktop")
    };
    desktop.join(file)
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
fn desktop_entry(python: &Path, play: &Path, project: &Path, icon: &Path) -> String {
    format!(
        "[Desktop Entry]\nType=Application\nName={NAME}\nComment=Play Streets of Rage\nExec={} {}\nPath={}\nIcon={}\nTerminal=false\nCategories=Game;\n",
        exec_quote(&python.to_string_lossy()),
        exec_quote(&play.to_string_lossy()),
        project.display(),
        icon.display(),
    )
}

fn sh_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

#[allow(dead_code)]
fn bundle_script(python: &Path, play: &Path, project: &Path) -> String {
    format!(
        "#!/bin/sh\ncd {}\nexec {} {}\n",
        sh_quote(&project.to_string_lossy()),
        sh_quote(&python.to_string_lossy()),
        sh_quote(&play.to_string_lossy()),
    )
}

#[allow(dead_code)]
const INFO_PLIST: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Streets of Rage</string>
    <key>CFBundleDisplayName</key><string>Streets of Rage</string>
    <key>CFBundleIdentifier</key><string>com.ruinelson.streetsofrage.launcher</string>
    <key>CFBundleExecutable</key><string>launcher</string>
    <key>CFBundleIconFile</key><string>icon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
"#;

/// An `.app` whose launcher runs play.py with the Python that has Tk.
#[allow(dead_code)]
fn write_bundle(bundle: &Path, python: &Path, play: &Path, project: &Path) -> Result<(), String> {
    let io = |e: std::io::Error| format!("cannot write {}: {e}", bundle.display());
    let _ = std::fs::remove_dir_all(bundle);
    std::fs::create_dir_all(bundle.join("Contents/MacOS")).map_err(io)?;
    std::fs::create_dir_all(bundle.join("Contents/Resources")).map_err(io)?;
    std::fs::write(bundle.join("Contents/Info.plist"), INFO_PLIST).map_err(io)?;
    std::fs::write(bundle.join("Contents/Resources/icon.icns"), ICON_ICNS).map_err(io)?;
    let launcher = bundle.join("Contents/MacOS/launcher");
    std::fs::write(&launcher, bundle_script(python, play, project)).map_err(io)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&launcher, std::fs::Permissions::from_mode(0o755)).map_err(io)?;
    }
    Ok(())
}

#[cfg(windows)]
fn create_windows(file: &Path, data: &Path, project: &Path, play: &Path) -> Result<(), String> {
    // pyw runs Python without a console window.
    let pyw = system::find_program("pyw").ok_or("Python's pyw launcher was not found; finish step 1 first")?;
    let icon = data.join("icon.ico");
    std::fs::write(&icon, ICON_ICO).map_err(|e| format!("cannot write {}: {e}", icon.display()))?;
    let script = "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:SOR_LNK); \
                  $s.TargetPath = $env:SOR_TARGET; $s.Arguments = $env:SOR_ARGS; $s.WorkingDirectory = $env:SOR_DIR; \
                  $s.IconLocation = $env:SOR_ICON; $s.Description = 'Play Streets of Rage'; $s.Save()";
    let output = system::command(Path::new("powershell"))
        .args(["-NoProfile", "-NonInteractive", "-Command", script])
        .env("SOR_LNK", file)
        .env("SOR_TARGET", &pyw)
        .env("SOR_ARGS", format!("-3 \"{}\"", play.display()))
        .env("SOR_DIR", project)
        .env("SOR_ICON", &icon)
        .output()
        .map_err(|e| e.to_string())?;
    if output.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_owned())
    }
}

#[cfg(target_os = "linux")]
fn create_linux(file: &Path, data: &Path, project: &Path, play: &Path) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    let (python, _) = dependencies::tk_python().ok_or("Python with Tk was not found; finish step 1 first")?;
    let icon = data.join("icon.png");
    std::fs::write(&icon, ICON_PNG).map_err(|e| format!("cannot write {}: {e}", icon.display()))?;
    std::fs::write(file, desktop_entry(&python, play, project, &icon)).map_err(|e| format!("cannot write {}: {e}", file.display()))?;
    std::fs::set_permissions(file, std::fs::Permissions::from_mode(0o755)).map_err(|e| e.to_string())?;
    // GNOME only runs a desktop file it trusts; other desktops ignore this.
    let _ = system::run("gio", &["set", &file.to_string_lossy(), "metadata::trusted", "true"]);
    Ok(())
}

fn create(desktop: &Path, data: &Path, project: &Path) -> Result<PathBuf, String> {
    system::refresh_path();
    let play = project.join("scripts").join("play.py");
    if !play.is_file() {
        return Err(format!("{} is not the project folder; redo step 2.", project.display()));
    }
    std::fs::create_dir_all(desktop).map_err(|e| format!("cannot create {}: {e}", desktop.display()))?;
    std::fs::create_dir_all(data).map_err(|e| format!("cannot create {}: {e}", data.display()))?;
    let file = shortcut_file(desktop);
    #[cfg(windows)]
    create_windows(&file, data, project, &play)?;
    #[cfg(target_os = "macos")]
    {
        let (python, _) = dependencies::tk_python().ok_or("Python with Tk was not found; finish step 1 first")?;
        write_bundle(&file, &python, &play, project)?;
    }
    #[cfg(target_os = "linux")]
    create_linux(&file, data, project, &play)?;
    let _ = data;
    Ok(file)
}

#[tauri::command]
pub fn create_shortcut(app: AppHandle, project: String) -> Result<Shortcut, String> {
    let data = app.path().app_local_data_dir().map_err(|e| e.to_string())?;
    let file = create(&desktop()?, &data, Path::new(&project))?;
    Ok(Shortcut { path: file.to_string_lossy().into_owned() })
}

/// The shortcut already on the desktop, if any.
#[tauri::command]
pub fn shortcut_status() -> Option<Shortcut> {
    let file = shortcut_file(&desktop().ok()?);
    file.exists().then(|| Shortcut { path: file.to_string_lossy().into_owned() })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quotes_paths_with_spaces_and_specials() {
        assert_eq!(exec_quote("/Users/a b/\"x\"$"), "\"/Users/a b/\\\"x\\\"\\$\"");
        assert_eq!(sh_quote("it's"), "'it'\\''s'");
        let entry = desktop_entry(Path::new("/usr/bin/python3"), Path::new("/a b/scripts/play.py"), Path::new("/a b"), Path::new("/i.png"));
        assert!(entry.contains("Exec=\"/usr/bin/python3\" \"/a b/scripts/play.py\"\n"));
        assert!(entry.contains("Path=/a b\n"));
    }

    #[test]
    fn the_bundle_has_what_macos_needs() {
        let root = std::env::temp_dir().join(format!("sor-builder-bundle-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let bundle = root.join("Streets of Rage.app");
        write_bundle(&bundle, Path::new("/usr/bin/python3"), Path::new("/p/scripts/play.py"), Path::new("/p")).unwrap();
        assert!(bundle.join("Contents/Info.plist").is_file());
        assert!(bundle.join("Contents/Resources/icon.icns").metadata().unwrap().len() > 1000);
        let launcher = std::fs::read_to_string(bundle.join("Contents/MacOS/launcher")).unwrap();
        assert!(launcher.contains("exec '/usr/bin/python3' '/p/scripts/play.py'"));
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(bundle.join("Contents/MacOS/launcher").metadata().unwrap().permissions().mode() & 0o111, 0o111);
        }
        std::fs::remove_dir_all(&root).unwrap();
    }

    /// Makes the real shortcut in a scratch desktop: `SOR_TEST_FOLDER=project SOR_TEST_DESKTOP=dir cargo test real_shortcut -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn creates_the_real_shortcut() {
        let project = std::env::var("SOR_TEST_FOLDER").expect("SOR_TEST_FOLDER");
        let desktop = PathBuf::from(std::env::var("SOR_TEST_DESKTOP").expect("SOR_TEST_DESKTOP"));
        let file = create(&desktop, &desktop.join("data"), Path::new(&project)).unwrap();
        println!("{}", file.display());
        assert!(file.exists());
    }

    #[test]
    fn refuses_a_folder_without_play_py() {
        let project = std::env::temp_dir().join(format!("sor-builder-shortcut-{}", std::process::id()));
        std::fs::create_dir_all(&project).unwrap();
        assert!(create(&project.join("desktop"), &project.join("data"), &project).is_err());
        std::fs::remove_dir_all(&project).unwrap();
    }
}
