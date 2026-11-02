//! The PlayStation 5 target: the same project built for the console inside a container, with
//! nothing but a container engine and git on the computer. These are the steps of
//! `scripts/ps5_wizzard.sh` (image, soundtrack, build, ZIP files, FTP upload, clean up), run here
//! with the same image and volume names as `scripts/build_ps5.py`.

use std::fs::File;
use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde::Serialize;
use tauri::ipc::Channel;
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipWriter};

use crate::sound::{self, Soundtrack};
use crate::{compile, script, stamp, system};

const IMAGE: &str = "sor-ps5-toolchain";
const BUILD_VOLUME: &str = "sor-ps5-build";
const TITLE_ID: &str = "PPSA99872";
const ZIP_HOMEBREW: &str = "StreetsOfRage-PS5-homebrew.zip";
const ZIP_DATA: &str = "StreetsOfRage-PS5-data.zip";
const FTP_ATTEMPTS: u32 = 3;

// ---------------------------------------------------------------------------------------------
// The container engine

pub enum Engine {
    Missing,
    /// A `docker` or `podman` command exists, but no engine answers.
    Stopped,
    Running { path: PathBuf, version: String },
}

/// The first of `docker` and `podman` whose engine is running (OrbStack and Podman Desktop provide `docker`).
pub fn engine() -> Engine {
    system::refresh_path();
    let mut installed = false;
    for name in ["docker", "podman"] {
        let Some(path) = system::find_program(name) else { continue };
        installed = true;
        if system::command(&path).arg("info").output().is_ok_and(|o| o.status.success()) {
            let version = system::command(&path)
                .arg("--version")
                .output()
                .ok()
                .and_then(|o| String::from_utf8_lossy(&o.stdout).lines().next().map(|l| l.trim().to_owned()))
                .unwrap_or_else(|| name.to_owned());
            return Engine::Running { path, version };
        }
    }
    if installed { Engine::Stopped } else { Engine::Missing }
}

fn running_engine() -> Result<PathBuf, String> {
    match engine() {
        Engine::Running { path, .. } => Ok(path),
        _ => Err("The container engine is not running; redo step 2.".into()),
    }
}

// ---------------------------------------------------------------------------------------------
// Paths and containers

fn sor_folder(project: &Path) -> PathBuf {
    project.join("StreetsOfRageRecompilation")
}

fn dist_folder(project: &Path) -> PathBuf {
    sor_folder(project).join("dist-ps5")
}

fn rom_file(project: &Path) -> PathBuf {
    sor_folder(project).join("rom").join("SOR.bin")
}

fn require_rom(project: &Path) -> Result<(), String> {
    if rom_file(project).is_file() { Ok(()) } else { Err("The ROM is not in the project yet; redo step 4.".into()) }
}

/// SELinux needs the workspace relabelled for the container to read it.
fn workspace_options() -> &'static str {
    #[cfg(target_os = "linux")]
    if system::first_line("getenforce", &[]).as_deref() == Some("Enforcing") {
        return ":z";
    }
    ""
}

/// `engine run --rm` on the toolchain image with the project as `/workspace` and the build volume as `/build`.
fn container(engine: &Path, project: &Path, args: &[&str]) -> Command {
    let mut command = system::command(engine);
    command
        .args(["run", "--rm", "-v"])
        .arg(format!("{}:/workspace{}", project.display(), workspace_options()))
        .args(["-v", &format!("{BUILD_VOLUME}:/build"), IMAGE])
        .args(args);
    command
}

/// Git on Windows checks files out with CRLF, which the shell scripts and the patch of the PS5
/// build cannot take inside a Linux container (`build-cpython.sh` seds the CPython version out of
/// `cmake/CPythonRuntime.cmake`). Returns how many files it changed.
fn unix_line_endings(sor: &Path) -> std::io::Result<usize> {
    fn visit(folder: &Path, recursive: bool, changed: &mut usize) -> std::io::Result<()> {
        let Ok(entries) = std::fs::read_dir(folder) else { return Ok(()) };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                if recursive {
                    visit(&path, true, changed)?;
                }
                continue;
            }
            let name = entry.file_name().to_string_lossy().into_owned();
            let extension = path.extension().map(|e| e.to_string_lossy().into_owned()).unwrap_or_default();
            if !(["sh", "site", "patch", "cmake"].contains(&extension.as_str()) || name == "Dockerfile") {
                continue;
            }
            let bytes = std::fs::read(&path)?;
            if !bytes.contains(&b'\r') {
                continue;
            }
            let mut clean = Vec::with_capacity(bytes.len());
            for (i, &byte) in bytes.iter().enumerate() {
                if byte == b'\r' && bytes.get(i + 1) == Some(&b'\n') {
                    continue;
                }
                clean.push(byte);
            }
            std::fs::write(&path, clean)?;
            *changed += 1;
        }
        Ok(())
    }
    let mut changed = 0;
    visit(&sor.join("prospero"), true, &mut changed)?;
    visit(&sor.join("cmake"), false, &mut changed)?;
    Ok(changed)
}

/// The image (built once, about 5 GB) and a check that the toolchain inside it works.
fn prepare(engine: &Path, project: &Path, progress: &(dyn Fn(String) + Sync)) -> Result<(), String> {
    let sor = sor_folder(project);
    let context = sor.join("prospero").join("docker");
    if !context.join("Dockerfile").is_file() {
        return Err(format!("{} is not the project folder, or has no PS5 port; redo step 3.", project.display()));
    }
    match unix_line_endings(&sor) {
        Ok(0) => {}
        Ok(count) => progress(format!("Set {count} build files to Unix line endings (Git on Windows had changed them)")),
        Err(error) => return Err(format!("could not fix the line endings of the build files: {error}")),
    }
    progress("Preparing the toolchain image (about 5 GB the first time)…".into());
    let mut build = system::command(engine);
    build
        .args(["build", "-t", IMAGE])
        .arg(&context)
        .env("DOCKER_BUILDKIT", "1")
        .env("BUILDKIT_PROGRESS", "plain");
    script::stream(build, "the toolchain image build", progress)?;
    progress("Checking the toolchain…".into());
    script::stream(container(engine, project, &["bash", "/opt/ps5/check-toolchain.sh"]), "the toolchain check", progress)
}

/// The containers run as root, so the files they write need handing back to the user. A rootless
/// engine already writes them as the user.
#[cfg(target_os = "linux")]
fn hand_back(engine: &Path, project: &Path, progress: &(dyn Fn(String) + Sync)) -> Result<(), String> {
    let rootless = system::command(engine)
        .args(["info", "--format", "{{.SecurityOptions}}"])
        .output()
        .is_ok_and(|o| String::from_utf8_lossy(&o.stdout).to_lowercase().contains("rootless"));
    if rootless {
        return Ok(());
    }
    let (Some(uid), Some(gid)) = (system::first_line("id", &["-u"]), system::first_line("id", &["-g"])) else {
        return Ok(());
    };
    progress("Giving you the files the container made…".into());
    let sor = "/workspace/StreetsOfRageRecompilation";
    let script = format!(
        "for path in {sor}/generated {sor}/dist-ps5 {sor}/rom/soundtrack; do [ -e \"$path\" ] && chown -R {uid}:{gid} \"$path\"; done; true"
    );
    script::stream(container(engine, project, &["sh", "-c", &script]), "giving you the files", progress)
}

#[cfg(not(target_os = "linux"))]
fn hand_back(_engine: &Path, _project: &Path, _progress: &(dyn Fn(String) + Sync)) -> Result<(), String> {
    Ok(())
}

// ---------------------------------------------------------------------------------------------
// Soundtrack

fn render_script(chip: &str) -> String {
    format!(
        r#"set -e
tool=/workspace/StreetsOfRageRecompilation/tools/soundtrack
rom=/workspace/StreetsOfRageRecompilation/rom/SOR.bin
out=/workspace/StreetsOfRageRecompilation/rom/soundtrack
cmake -S "$tool" -B /build/soundtrack -DCMAKE_BUILD_TYPE=Release
cmake --build /build/soundtrack --parallel
rm -rf "$out.rendering"
/build/soundtrack/sor_soundtrack --rom "$rom" --out "$out.rendering" --chip {chip}
rm -rf "$out"
mv "$out.rendering" "$out"
"#
    )
}

fn render_soundtrack(project: &Path, chip: &str, progress: &(dyn Fn(String) + Sync)) -> Result<Soundtrack, String> {
    if !sound::CHIPS.contains(&chip) {
        return Err(format!("unknown chip {chip}"));
    }
    require_rom(project)?;
    let engine = running_engine()?;
    prepare(&engine, project, progress)?;
    let rendered_from = sound::version(project);
    progress("Rendering the soundtrack…".into());
    script::stream(container(&engine, project, &["bash", "-c", &render_script(chip)]), "the soundtrack render", progress)?;
    hand_back(&engine, project, progress)?;
    stamp::write(&sound::soundtrack_folder(project), rendered_from);
    sound::status(project).ok_or_else(|| "The renderer finished but produced no soundtrack.".into())
}

// ---------------------------------------------------------------------------------------------
// Build

#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Title {
    pub folder: String,
    /// Built from another version of the project than the one on disk now.
    pub outdated: bool,
}

fn title_status(project: &Path) -> Option<Title> {
    let dist = dist_folder(project);
    if !dist.join(TITLE_ID).join("eboot.bin").is_file() || !dist.join("data-sor").join("ai-code").is_dir() {
        return None;
    }
    Some(Title {
        folder: dist.to_string_lossy().into_owned(),
        outdated: !stamp::is_current(&dist, compile::version(project)),
    })
}

fn build(project: &Path, progress: &(dyn Fn(String) + Sync)) -> Result<Title, String> {
    require_rom(project)?;
    let engine = running_engine()?;
    prepare(&engine, project, progress)?;
    let built_from = compile::version(project);
    progress("Generating the C++ port from your ROM…".into());
    script::stream(
        container(&engine, project, &["env", "PYTHONDONTWRITEBYTECODE=1", "python3", "/workspace/scripts/generate_cpp.py"]),
        "the C++ generation",
        progress,
    )?;
    progress("Compiling the PS5 title…".into());
    script::stream(
        container(&engine, project, &["bash", "/workspace/StreetsOfRageRecompilation/prospero/tools/build.sh"]),
        "the PS5 build",
        progress,
    )?;
    hand_back(&engine, project, progress)?;
    stamp::write(&dist_folder(project), built_from);
    title_status(project).ok_or_else(|| "The build finished but its files are not in dist-ps5.".into())
}

// ---------------------------------------------------------------------------------------------
// The files for the console: /data/homebrew gets the title, /data gets the folder `sor`.

#[derive(Debug)]
struct Entry {
    local: PathBuf,
    /// Path inside the ZIP, and below `/data/homebrew` or `/data` on the console.
    name: String,
}

/// Every file under `root` as `prefix/relative/path`, sorted; no dot files, no `__pycache__`.
fn tree(root: &Path, prefix: &str, files: &mut Vec<Entry>) -> io::Result<()> {
    let mut entries: Vec<_> = std::fs::read_dir(root)?.collect::<Result<_, _>>()?;
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        let name = entry.file_name().to_string_lossy().into_owned();
        if name.starts_with('.') || name == "__pycache__" {
            continue;
        }
        let path = entry.path();
        let name = format!("{prefix}/{name}");
        if path.is_dir() {
            tree(&path, &name, files)?;
        } else {
            files.push(Entry { local: path, name });
        }
    }
    Ok(())
}

fn homebrew_files(project: &Path) -> io::Result<Vec<Entry>> {
    let mut files = Vec::new();
    tree(&dist_folder(project).join(TITLE_ID), TITLE_ID, &mut files)?;
    Ok(files)
}

fn data_files(project: &Path) -> io::Result<Vec<Entry>> {
    let dist = dist_folder(project);
    let mut files = Vec::new();
    tree(&dist.join("data-sor").join("ai-code"), "sor/ai-code", &mut files)?;
    tree(&dist.join("data-sor").join("python"), "sor/python", &mut files)?;
    tree(&sound::soundtrack_folder(project), "sor/soundtrack", &mut files)?;
    files.push(Entry { local: rom_file(project), name: "sor/SOR.bin".into() });
    Ok(files)
}

/// What the console needs, or why it cannot be had yet.
fn deliverables(project: &Path) -> Result<(Vec<Entry>, Vec<Entry>), String> {
    if title_status(project).is_none() {
        return Err("The PS5 title is not built yet; redo step 6.".into());
    }
    if !sound::soundtrack_folder(project).join("manifest.tsv").is_file() {
        return Err("The soundtrack is not rendered yet; redo step 5.".into());
    }
    require_rom(project)?;
    let homebrew = homebrew_files(project).map_err(|e| e.to_string())?;
    let data = data_files(project).map_err(|e| e.to_string())?;
    Ok((homebrew, data))
}

#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct ZipFile {
    pub path: String,
    pub size: u64,
}

fn write_zip(path: &Path, files: &[Entry], done: &mut usize, total: usize, progress: &dyn Fn(String)) -> Result<ZipFile, String> {
    let fail = |e: &dyn std::fmt::Display| format!("could not write {}: {e}", path.display());
    let mut zip = ZipWriter::new(File::create(path).map_err(|e| fail(&e))?);
    for file in files {
        *done += 1;
        progress(format!("[{done}/{total}] {}", file.name));
        // Already compressed: the console unzips faster, and the zip is no smaller.
        let method = if file.name.ends_with(".flac") { CompressionMethod::Stored } else { CompressionMethod::Deflated };
        #[allow(unused_mut)]
        let mut options = SimpleFileOptions::default().compression_method(method).large_file(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = file.local.metadata().map_err(|e| fail(&e))?.permissions().mode();
            options = options.unix_permissions(mode & 0o777);
        }
        // Entry names always use `/`, whatever the system.
        zip.start_file(file.name.as_str(), options).map_err(|e| fail(&e))?;
        io::copy(&mut File::open(&file.local).map_err(|e| fail(&e))?, &mut zip).map_err(|e| fail(&e))?;
    }
    zip.finish().map_err(|e| fail(&e))?;
    let size = path.metadata().map(|m| m.len()).unwrap_or(0);
    Ok(ZipFile { path: path.to_string_lossy().into_owned(), size })
}

fn make_zips(project: &Path, folder: &Path, progress: &dyn Fn(String)) -> Result<Vec<ZipFile>, String> {
    let (homebrew, data) = deliverables(project)?;
    if !folder.is_dir() {
        return Err(format!("{} is not a folder.", folder.display()));
    }
    let total = homebrew.len() + data.len();
    let mut done = 0;
    Ok(vec![
        write_zip(&folder.join(ZIP_HOMEBREW), &homebrew, &mut done, total, progress)?,
        write_zip(&folder.join(ZIP_DATA), &data, &mut done, total, progress)?,
    ])
}

// ---------------------------------------------------------------------------------------------
// FTP

fn curl() -> Result<PathBuf, String> {
    system::find_program("curl").ok_or_else(|| "curl was not found; it is needed to send the files by FTP.".to_owned())
}

/// A host name or IPv4 address, and a port.
fn ftp_base(host: &str, port: &str) -> Result<String, String> {
    let host = host.trim();
    if host.is_empty() || !host.chars().all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-') {
        return Err("That does not look like an address.".into());
    }
    let port: u16 = port.trim().parse().map_err(|_| "A port is a number.".to_owned())?;
    Ok(format!("ftp://{host}:{port}"))
}

/// Percent-encodes everything in a path but unreserved characters and `/`.
fn url_path(path: &str) -> String {
    let mut encoded = String::new();
    for byte in path.bytes() {
        if byte.is_ascii_alphanumeric() || b"/-._~".contains(&byte) {
            encoded.push(byte as char);
        } else {
            encoded.push_str(&format!("%{byte:02X}"));
        }
    }
    encoded
}

fn probe(host: &str, port: &str) -> Result<(), String> {
    let url = format!("{}/", ftp_base(host, port)?);
    let output = system::command(&curl()?)
        .args(["-sS", "--connect-timeout", "8", "--max-time", "15", "--list-only", &url])
        .output()
        .map_err(|e| e.to_string())?;
    if output.status.success() {
        Ok(())
    } else {
        Err(format!(
            "The console did not answer ({}). Check that ftpsrv is running on it, that this computer is on the same network, and the address.",
            String::from_utf8_lossy(&output.stderr).trim()
        ))
    }
}

fn upload(project: &Path, host: &str, port: &str, progress: &dyn Fn(String)) -> Result<usize, String> {
    let base = ftp_base(host, port)?;
    let curl = curl()?;
    let (homebrew, data) = deliverables(project)?;
    // The program goes last, so a console never sees a title whose data is not there yet.
    let (eboot, homebrew): (Vec<_>, Vec<_>) = homebrew.into_iter().partition(|e| e.name == format!("{TITLE_ID}/eboot.bin"));
    let list: Vec<(PathBuf, String)> = data
        .into_iter()
        .map(|e| (e.local, format!("/data/{}", e.name)))
        .chain(homebrew.into_iter().chain(eboot).map(|e| (e.local, format!("/data/homebrew/{}", e.name))))
        .collect();
    for (index, (local, remote)) in list.iter().enumerate() {
        progress(format!("[{}/{}] {remote}", index + 1, list.len()));
        let mut attempt = 1;
        loop {
            let output = system::command(&curl)
                .args(["-sS", "--connect-timeout", "15", "--ftp-create-dirs", "-T"])
                .arg(local)
                .arg(format!("{base}{}", url_path(remote)))
                .output()
                .map_err(|e| e.to_string())?;
            if output.status.success() {
                break;
            }
            if attempt >= FTP_ATTEMPTS {
                return Err(format!(
                    "Could not send {remote}\n{}\nThe upload stopped. Do it again: it sends everything again.",
                    String::from_utf8_lossy(&output.stderr).trim()
                ));
            }
            attempt += 1;
            std::thread::sleep(std::time::Duration::from_secs(2));
        }
    }
    Ok(list.len())
}

// ---------------------------------------------------------------------------------------------
// Clean up: the container image, the build volume and `dist-ps5/`; the ROM, `generated/` and the
// soundtrack stay.

fn clean_up(project: &Path) -> Result<Vec<String>, String> {
    let engine = running_engine()?;
    let mut removed = Vec::new();
    let engine_run = |args: &[&str]| system::command(&engine).args(args).output().is_ok_and(|o| o.status.success());
    if engine_run(&["image", "rm", "-f", IMAGE]) {
        removed.push("The container image".to_owned());
    }
    if engine_run(&["volume", "rm", "-f", BUILD_VOLUME]) {
        removed.push("The build volume".to_owned());
    }
    let dist = dist_folder(project);
    if dist.exists() {
        std::fs::remove_dir_all(&dist).map_err(|e| format!("could not remove {}: {e}", dist.display()))?;
        removed.push("The built title".to_owned());
    }
    Ok(removed)
}

// ---------------------------------------------------------------------------------------------
// Commands

#[tauri::command]
pub fn ps5_title_status(project: String) -> Option<Title> {
    title_status(Path::new(&project))
}

#[tauri::command]
pub async fn ps5_render_soundtrack(project: String, chip: String, progress: Channel<String>) -> Result<Soundtrack, String> {
    tauri::async_runtime::spawn_blocking(move || {
        render_soundtrack(Path::new(&project), &chip, &|line| {
            let _ = progress.send(line);
        })
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn ps5_build(project: String, progress: Channel<String>) -> Result<Title, String> {
    tauri::async_runtime::spawn_blocking(move || {
        build(Path::new(&project), &|line| {
            let _ = progress.send(line);
        })
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn ps5_make_zips(project: String, folder: String, progress: Channel<String>) -> Result<Vec<ZipFile>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        make_zips(Path::new(&project), Path::new(&folder), &|line| {
            let _ = progress.send(line);
        })
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn ps5_probe_console(host: String, port: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || probe(&host, &port)).await.map_err(|e| e.to_string())?
}

/// Sends everything to the console; resolves with the number of files.
#[tauri::command]
pub async fn ps5_upload(project: String, host: String, port: String, progress: Channel<String>) -> Result<usize, String> {
    tauri::async_runtime::spawn_blocking(move || {
        upload(Path::new(&project), &host, &port, &|line| {
            let _ = progress.send(line);
        })
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn ps5_clean_up(project: String) -> Result<Vec<String>, String> {
    tauri::async_runtime::spawn_blocking(move || clean_up(Path::new(&project))).await.map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;

    fn scratch(name: &str) -> PathBuf {
        let folder = std::env::temp_dir().join(format!("sor-builder-ps5-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&folder);
        std::fs::create_dir_all(&folder).unwrap();
        folder
    }

    fn write(folder: &Path, file: &str, bytes: &[u8]) {
        let path = folder.join(file);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, bytes).unwrap();
    }

    #[test]
    fn crlf_goes_in_build_files_only() {
        let sor = scratch("crlf");
        write(&sor, "prospero/tools/build.sh", b"a\r\nb\r\n");
        write(&sor, "prospero/docker/Dockerfile", b"FROM x\r\n");
        write(&sor, "prospero/notes.txt", b"keep\r\n");
        write(&sor, "cmake/CPythonRuntime.cmake", b"set(V 1)\r\n");
        write(&sor, "cmake/sub/deep.cmake", b"x\r\n");
        assert_eq!(unix_line_endings(&sor).unwrap(), 3);
        assert_eq!(std::fs::read(sor.join("prospero/tools/build.sh")).unwrap(), b"a\nb\n");
        assert_eq!(std::fs::read(sor.join("prospero/notes.txt")).unwrap(), b"keep\r\n");
        assert_eq!(std::fs::read(sor.join("cmake/sub/deep.cmake")).unwrap(), b"x\r\n");
        assert_eq!(unix_line_endings(&sor).unwrap(), 0);
        std::fs::remove_dir_all(sor).unwrap();
    }

    #[test]
    fn a_project_with_a_built_title_zips_into_two_files() {
        let project = scratch("zip");
        let dist = dist_folder(&project);
        write(&dist, "PPSA99872/eboot.bin", b"elf");
        write(&dist, "PPSA99872/sce_sys/param.json", b"{}");
        write(&dist, "PPSA99872/.hidden", b"x");
        write(&dist, "data-sor/ai-code/sor_ai/__pycache__/x.pyc", b"x");
        write(&dist, "data-sor/ai-code/sor_ai/main.py", b"print()");
        write(&dist, "data-sor/python/lib/os.py", b"");
        write(&sound::soundtrack_folder(&project), "music.flac", b"flac");
        write(&sound::soundtrack_folder(&project), "manifest.tsv", b"");
        write(&rom_file(&project).parent().unwrap().to_path_buf(), "SOR.bin", b"rom");
        let (homebrew, data) = deliverables(&project).unwrap();
        let names = |files: &[Entry]| files.iter().map(|e| e.name.clone()).collect::<Vec<_>>();
        assert_eq!(names(&homebrew), ["PPSA99872/eboot.bin", "PPSA99872/sce_sys/param.json"]);
        assert_eq!(
            names(&data),
            ["sor/ai-code/sor_ai/main.py", "sor/python/lib/os.py", "sor/soundtrack/manifest.tsv", "sor/soundtrack/music.flac", "sor/SOR.bin"]
        );

        let out = scratch("zip-out");
        let zips = make_zips(&project, &out, &|_| {}).unwrap();
        assert_eq!(zips.len(), 2);
        let archive = zip::ZipArchive::new(File::open(out.join(ZIP_DATA)).unwrap()).unwrap();
        let mut entries: Vec<_> = archive.file_names().map(str::to_owned).collect();
        entries.sort();
        assert!(entries.iter().all(|name| name.starts_with("sor/") && !name.contains('\\')));
        assert_eq!(entries.len(), 5);
        let mut archive = archive;
        let mut text = String::new();
        archive.by_name("sor/ai-code/sor_ai/main.py").unwrap().read_to_string(&mut text).unwrap();
        assert_eq!(text, "print()");
        assert_eq!(archive.by_name("sor/soundtrack/music.flac").unwrap().compression(), CompressionMethod::Stored);
        std::fs::remove_dir_all(project).unwrap();
        std::fs::remove_dir_all(out).unwrap();
    }

    #[test]
    fn nothing_is_delivered_before_the_build_and_the_soundtrack() {
        let project = scratch("early");
        assert!(deliverables(&project).unwrap_err().contains("step 6"));
        std::fs::remove_dir_all(project).unwrap();
    }

    #[test]
    fn ftp_addresses_and_paths() {
        assert_eq!(ftp_base(" 192.168.1.50 ", "2121").unwrap(), "ftp://192.168.1.50:2121");
        assert!(ftp_base("", "2121").is_err());
        assert!(ftp_base("a b", "2121").is_err());
        assert!(ftp_base("ps5", "port").is_err());
        assert_eq!(url_path("/data/sor/My File#1?.bin"), "/data/sor/My%20File%231%3F.bin");
        assert_eq!(url_path("/data/á"), "/data/%C3%A1");
    }

    #[test]
    fn the_soundtrack_script_names_the_chip() {
        assert!(render_script("ym2612").contains("--chip ym2612"));
    }
}
