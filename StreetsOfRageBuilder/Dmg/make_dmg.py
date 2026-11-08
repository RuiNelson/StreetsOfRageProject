#!/usr/bin/env python3
"""Builds the Builder's macOS disk image (replaces the one Tauri makes).

The image holds the Builder's .app and a copy of "I am sure I want to open this App"
(https://github.com/RuiNelson/IAmSureIWantToOpenThisApp), which removes the quarantine, with a
"drop into" arrow from the first to the second. Layout: `settings.py` (dmgbuild) and `background.tiff`
(drawn by `background.swift`). Needs `pip install dmgbuild`.

    make_dmg.py --app "Streets of Rage Builder.app" --out StreetsOfRageBuilder.dmg
"""
import argparse
import hashlib
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
HELPER_TAG = "v1.1.1"
HELPER_URL = (
    "https://github.com/RuiNelson/IAmSureIWantToOpenThisApp/releases/download/"
    f"{HELPER_TAG}/I_am_sure_I_want_to_open_this_App.zip"
)
HELPER_SHA256 = "35febcba579630c2f3c521bae5ea9b4f505c81e4b5c9dba0da9831774b86fde2"
HELPER_APP = "I am sure I want to open this App.app"
VOLUME_NAME = "Streets of Rage Builder"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app", required=True, type=Path, help="the Builder's .app bundle")
    parser.add_argument("--out", required=True, type=Path, help="the .dmg to write")
    args = parser.parse_args()
    if not args.app.is_dir():
        sys.exit(f"not an app bundle: {args.app}")

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "helper.zip"
        urllib.request.urlretrieve(HELPER_URL, archive)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != HELPER_SHA256:
            sys.exit(f"{HELPER_URL}: SHA-256 {digest}, expected {HELPER_SHA256}")
        # ditto keeps the helper's code signature, which unzip would break.
        subprocess.run(["ditto", "-x", "-k", str(archive), tmp], check=True)
        helper = Path(tmp) / HELPER_APP
        if not helper.is_dir():
            sys.exit(f"{HELPER_APP} is not in {HELPER_URL}")

        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.unlink(missing_ok=True)
        subprocess.run(
            [
                sys.executable, "-m", "dmgbuild",
                "-s", str(HERE / "settings.py"),
                "-D", f"app={args.app.resolve()}",
                "-D", f"helper={helper}",
                "-D", f"background={HERE / 'background.tiff'}",
                VOLUME_NAME, str(args.out),
            ],
            check=True,
        )
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
