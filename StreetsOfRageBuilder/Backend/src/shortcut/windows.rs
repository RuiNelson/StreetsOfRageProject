//! Windows: two `.lnk` on the desktop, pointing into the project.

use std::path::{Path, PathBuf};

use super::{entries, game_options, Inputs};
use crate::system;

pub const EXTENSION: &str = "lnk";
pub const LOCATIONS: &[Option<&str>] = &[None];
const ICON_ICO: &[u8] = include_bytes!("../../icons/icon.ico");

/// The desktop folder (it may be redirected, for example to OneDrive).
pub fn destination(_location: Option<&str>) -> Result<PathBuf, String> {
    let output = system::run("powershell", &["-NoProfile", "-NonInteractive", "-Command", "[Environment]::GetFolderPath('Desktop')"])
        .ok_or("PowerShell was not found")?;
    let path = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    if path.is_empty() {
        return Err("cannot find the desktop folder".into());
    }
    Ok(PathBuf::from(path))
}

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

pub fn create(desktop: &Path, data: &Path, inputs: &Inputs) -> Result<(), String> {
    // pyw runs Python without a console window.
    let pyw = system::find_program("pyw").ok_or("Python's pyw launcher was not found; finish step 1 first")?;
    let icon = data.join("icon.ico");
    std::fs::write(&icon, ICON_ICO).map_err(|e| format!("cannot write {}: {e}", icon.display()))?;
    let [game, launcher] = entries(desktop, EXTENSION);
    let options: Vec<String> = game_options(inputs).iter().map(|(option, value)| format!("{option} \"{}\"", value.display())).collect();
    write_lnk(&game, &inputs.sor, &options.join(" "), &inputs.root, &icon, "Play Streets of Rage")?;
    write_lnk(&launcher, &pyw, &format!("-3 \"{}\"", inputs.play.display()), &inputs.root, &icon, "Open the Streets of Rage launcher")
}
