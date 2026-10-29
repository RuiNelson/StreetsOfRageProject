//! Step 3: the user's own ROM. It is verified by CRC32 against the dump the project was
//! recompiled from, then copied to where the project's scripts look for it
//! (`StreetsOfRageRecompilation/rom/SOR.bin`).

use std::path::Path;

use crc::{CRC_32_ISO_HDLC, Crc};
use serde::Serialize;

/// CRC32 of the project's `SOR.bin` (512 KiB, raw big-endian dump).
const EXPECTED_CRC: u32 = 0x4052_E845;
/// Nothing a Mega Drive game needs is bigger; do not read a stray huge file into memory.
const MAX_SIZE: u64 = 16 * 1024 * 1024;
const SMD_HEADER: usize = 512;
const SMD_BLOCK: usize = 16 * 1024;
const CRC32: Crc<u32> = Crc::<u32>::new(&CRC_32_ISO_HDLC);

#[derive(Serialize, Clone, Copy, PartialEq, Debug)]
#[serde(rename_all = "lowercase")]
pub enum RomState {
    /// The CRC32 matches: this is the dump the project needs.
    Ok,
    /// A Super Magic Drive dump (interleaved, 512-byte header): must be converted to a raw dump.
    Smd,
    /// Anything else: not the game, or a version of the cartridge the project does not support.
    Mismatch,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RomReport {
    pub file_name: String,
    pub size: u64,
    /// Eight hex digits; empty when the file was too big to read.
    pub crc: String,
    pub state: RomState,
}

/// Super Magic Drive files: a 512-byte header (block count, 0x03 for a Mega Drive ROM, the
/// 0xAA 0xBB signature) followed by 16 KiB interleaved blocks.
fn looks_like_smd(data: &[u8]) -> bool {
    data.len() > SMD_HEADER
        && (data.len() - SMD_HEADER) % SMD_BLOCK == 0
        && data[1] == 0x03
        && data[8] == 0xAA
        && data[9] == 0xBB
}

fn classify(data: &[u8], expected: u32) -> (RomState, u32) {
    let crc = CRC32.checksum(data);
    let state = if crc == expected {
        RomState::Ok
    } else if looks_like_smd(data) {
        RomState::Smd
    } else {
        RomState::Mismatch
    };
    (state, crc)
}

fn inspect(path: &Path) -> Result<(RomReport, Option<Vec<u8>>), String> {
    let file_name = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
    let size = std::fs::metadata(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?.len();
    if size > MAX_SIZE {
        return Ok((RomReport { file_name, size, crc: String::new(), state: RomState::Mismatch }, None));
    }
    let data = std::fs::read(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    let (state, crc) = classify(&data, EXPECTED_CRC);
    Ok((RomReport { file_name, size, crc: format!("{crc:08X}"), state }, Some(data)))
}

fn installed_path(project: &Path) -> std::path::PathBuf {
    project.join("StreetsOfRageRecompilation").join("rom").join("SOR.bin")
}

/// Verify `rom`; when it is the right dump, copy it into the project.
fn use_rom_in(rom: &Path, project: &Path) -> Result<RomReport, String> {
    let (report, data) = inspect(rom)?;
    if let (RomState::Ok, Some(data)) = (report.state, data) {
        let target = installed_path(project);
        let folder = target.parent().expect("the target has a folder");
        if !project.join("StreetsOfRageRecompilation").is_dir() {
            return Err(format!("{} is not the project folder; redo step 2.", project.display()));
        }
        std::fs::create_dir_all(folder).map_err(|e| format!("cannot create {}: {e}", folder.display()))?;
        std::fs::write(&target, data).map_err(|e| format!("cannot write {}: {e}", target.display()))?;
    }
    Ok(report)
}

#[tauri::command]
pub fn use_rom(rom: String, project: String) -> Result<RomReport, String> {
    use_rom_in(Path::new(&rom), Path::new(&project))
}

/// The ROM already in the project, if it is the right one (coming back to the step, or a later run).
#[tauri::command]
pub fn installed_rom(project: String) -> Option<RomReport> {
    let (report, _) = inspect(&installed_path(Path::new(&project))).ok()?;
    (report.state == RomState::Ok).then_some(report)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crc_matches_the_standard_check_value() {
        assert_eq!(CRC32.checksum(b"123456789"), 0xCBF4_3926);
    }

    #[test]
    fn classifies_by_crc_and_recognises_smd() {
        let (state, _) = classify(b"123456789", 0xCBF4_3926);
        assert_eq!(state, RomState::Ok);
        assert_eq!(classify(b"123456789", EXPECTED_CRC).0, RomState::Mismatch);

        let mut smd = vec![0u8; SMD_HEADER + SMD_BLOCK * 2];
        smd[1] = 0x03;
        smd[8] = 0xAA;
        smd[9] = 0xBB;
        assert_eq!(classify(&smd, EXPECTED_CRC).0, RomState::Smd);
        smd.push(0); // no longer whole blocks
        assert_eq!(classify(&smd, EXPECTED_CRC).0, RomState::Mismatch);
    }

    #[test]
    fn copies_only_the_right_dump() {
        let root = std::env::temp_dir().join(format!("sor-builder-rom-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let project = root.join("project");
        std::fs::create_dir_all(project.join("StreetsOfRageRecompilation")).unwrap();

        let wrong = root.join("wrong.md");
        std::fs::write(&wrong, b"not a rom").unwrap();
        let report = use_rom_in(&wrong, &project).unwrap();
        assert_eq!(report.state, RomState::Mismatch);
        assert!(!installed_path(&project).exists());
        assert!(installed_rom(project.to_string_lossy().into_owned()).is_none());

        // The real dump, when this checkout has it (it is never versioned).
        let real = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../StreetsOfRageRecompilation/rom/SOR.bin");
        if real.is_file() {
            let report = use_rom_in(&real, &project).unwrap();
            assert_eq!(report.state, RomState::Ok, "crc {}", report.crc);
            assert_eq!(report.crc, "4052E845");
            assert!(installed_rom(project.to_string_lossy().into_owned()).is_some());
        }
        std::fs::remove_dir_all(&root).unwrap();
    }
}
