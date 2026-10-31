//! Linux: two `.desktop` files on the desktop, pointing into the project.

use std::path::{Path, PathBuf};

use super::{entries, game_options, Inputs, GAME, LAUNCHER};
use crate::{dependencies, system};

pub const EXTENSION: &str = "desktop";
pub const LOCATIONS: &[Option<&str>] = &[None];
const ICON_PNG: &[u8] = include_bytes!("../../icons/icon.png");

pub fn desktop() -> Result<PathBuf, String> {
    if let Some(output) = system::run("xdg-user-dir", &["DESKTOP"]) {
        let path = String::from_utf8_lossy(&output.stdout).trim().to_owned();
        if !path.is_empty() && Path::new(&path).is_dir() {
            return Ok(PathBuf::from(path));
        }
    }
    let home = std::env::var_os("HOME").ok_or("cannot find the desktop folder")?;
    Ok(PathBuf::from(home).join("Desktop"))
}

pub fn destination(_location: Option<&str>, desktop: &Path) -> PathBuf {
    desktop.to_owned()
}

/// Quote a value for the `Exec` key of a desktop entry.
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

fn desktop_entry(name: &str, comment: &str, command: &[&Path], project: &Path, icon: &Path) -> String {
    let exec: Vec<String> = command.iter().map(|part| exec_quote(&part.to_string_lossy())).collect();
    format!(
        "[Desktop Entry]\nType=Application\nName={name}\nComment={comment}\nExec={}\nPath={}\nIcon={}\nTerminal=false\nCategories=Game;\n",
        exec.join(" "),
        project.display(),
        icon.display(),
    )
}

fn game_desktop_entry(inputs: &Inputs, icon: &Path) -> String {
    let mut command: Vec<&Path> = vec![&inputs.sor];
    for (option, value) in game_options(inputs) {
        command.push(Path::new(option));
        command.push(value);
    }
    desktop_entry(GAME, "Play Streets of Rage", &command, &inputs.root, icon)
}

pub fn create(desktop: &Path, data: &Path, inputs: &Inputs) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    let (python, _) = dependencies::tk_python().ok_or("Python with Tk was not found; finish step 1 first")?;
    let icon = data.join("icon.png");
    std::fs::write(&icon, ICON_PNG).map_err(|e| format!("cannot write {}: {e}", icon.display()))?;
    let [game, launcher] = entries(desktop, EXTENSION);
    let launcher_entry = desktop_entry(LAUNCHER, "Open the Streets of Rage launcher", &[python.as_path(), inputs.play.as_path()], &inputs.root, &icon);
    for (file, entry) in [(&game, game_desktop_entry(inputs, &icon)), (&launcher, launcher_entry)] {
        std::fs::write(file, entry).map_err(|e| format!("cannot write {}: {e}", file.display()))?;
        std::fs::set_permissions(file, std::fs::Permissions::from_mode(0o755)).map_err(|e| e.to_string())?;
        // GNOME only runs a desktop file it trusts; other desktops ignore this.
        let _ = system::run("gio", &["set", &file.to_string_lossy(), "metadata::trusted", "true"]);
    }
    Ok(())
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
}
