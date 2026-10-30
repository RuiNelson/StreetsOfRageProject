//! Which version of the project a build or a render came from. The output folders are ignored by
//! git, so an update of the project leaves them behind; a stamp next to the output records the
//! revision it was made from, and an output whose stamp differs (or is missing) is out of date.

use std::path::Path;

const FILE: &str = ".builder-version";

/// Record `version` in `folder` (nothing when git could not tell the version).
pub fn write(folder: &Path, version: Option<String>) {
    if let Some(version) = version {
        let _ = std::fs::write(folder.join(FILE), version);
    }
}

/// Whether the output in `folder` was made from `version`. When git cannot tell the current
/// version there is nothing to compare, so the output is accepted.
pub fn is_current(folder: &Path, version: Option<String>) -> bool {
    match version {
        None => true,
        Some(version) => std::fs::read_to_string(folder.join(FILE)).is_ok_and(|stamp| stamp.trim() == version),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_missing_or_different_stamp_is_out_of_date() {
        let folder = std::env::temp_dir().join(format!("sor-builder-stamp-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&folder);
        std::fs::create_dir_all(&folder).unwrap();
        assert!(!is_current(&folder, Some("abc".into())));
        write(&folder, Some("abc".into()));
        assert!(is_current(&folder, Some("abc".into())));
        assert!(!is_current(&folder, Some("def".into())));
        assert!(is_current(&folder, None));
        std::fs::remove_dir_all(&folder).unwrap();
    }
}
