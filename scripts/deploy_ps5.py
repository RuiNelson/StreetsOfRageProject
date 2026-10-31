#!/usr/bin/env python3
"""Copy the PS5 title and its files to a console over FTP (ftpsrv, port 2121).

Close the title on the console first. scripts/build_ps5.py makes what this sends, and the ROM
and the soundtrack come from rom/. A file already on the console with the same size is left
alone, except the program, its home-screen files and the AI, which are always sent. Nothing on
the console is removed, so saved settings, .pyc files and ai.log stay.
"""

from __future__ import annotations

import argparse
import ftplib
import os
import sys
from pathlib import Path, PurePosixPath

from _common import META_ROOT

RECOMPILATION = META_ROOT / "StreetsOfRageRecompilation"
DIST = RECOMPILATION / "dist-ps5"
TITLE_ID = "PPSA99872"
HOMEBREW = PurePosixPath("/data/homebrew") / TITLE_ID
DATA = PurePosixPath("/data/sor")


def files_under(local_root: Path, remote_root: PurePosixPath) -> list[tuple[Path, PurePosixPath]]:
    found = []
    for directory, subdirectories, names in os.walk(local_root):
        subdirectories[:] = sorted(name for name in subdirectories if name != "__pycache__")
        for name in sorted(names):
            if name.startswith("."):  # .DS_Store and the like
                continue
            local = Path(directory) / name
            found.append((local, remote_root / local.relative_to(local_root).as_posix()))
    return found


class Console:
    def __init__(self, host: str, port: int) -> None:
        self.ftp = ftplib.FTP()
        self.ftp.connect(host, port, timeout=30)
        self.ftp.login()
        self.listings: dict[PurePosixPath, dict[str, int] | None] = {}

    def size(self, path: PurePosixPath) -> int | None:
        """The file's size on the console, or None when it is not there."""
        if path.parent not in self.listings:
            try:
                self.listings[path.parent] = {
                    name: int(facts.get("size", -1))
                    for name, facts in self.ftp.mlsd(str(path.parent))
                    if facts.get("type") == "file"
                }
            except ftplib.error_perm:
                self.listings[path.parent] = None
        listing = self.listings[path.parent]
        return listing.get(path.name) if listing is not None else None

    def make_folders(self, directory: PurePosixPath) -> None:
        for folder in [*reversed(directory.parents), directory]:
            if self.listings.get(folder) is None and str(folder) != "/":
                try:
                    self.ftp.mkd(str(folder))
                except ftplib.error_perm:
                    pass  # it is there already
                self.listings.setdefault(folder, {})
                if self.listings[folder] is None:
                    self.listings[folder] = {}

    def send(self, local: Path, remote: PurePosixPath) -> None:
        self.make_folders(remote.parent)
        with local.open("rb") as file:
            self.ftp.storbinary(f"STOR {remote}", file, blocksize=1024 * 1024)
        self.listings[remote.parent][remote.name] = local.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=os.environ.get("PS5_HOST"), help="The console's address (default: $PS5_HOST)")
    parser.add_argument("--port", type=int, default=2121, help="Its FTP port")
    parser.add_argument("--rom", type=Path, default=RECOMPILATION / "rom" / "SOR.bin", help="The ROM to copy")
    parser.add_argument("--soundtrack", type=Path, default=RECOMPILATION / "rom" / "soundtrack", help="The soundtrack folder to copy")
    parser.add_argument("--force", action="store_true", help="Send every file, whatever its size on the console")
    parser.add_argument("--dry-run", action="store_true", help="Say what would be sent, and send nothing")
    arguments = parser.parse_args()
    if not arguments.host:
        parser.error("say which console: --host ADDRESS, or PS5_HOST")

    title = DIST / TITLE_ID
    data = DIST / "data-sor"
    if not (title / "eboot.bin").is_file() or not data.is_dir():
        print("Nothing built: run scripts/build_ps5.py first", file=sys.stderr)
        return 1

    # The program last: a title does not start half copied.
    always = [
        *files_under(data / "ai-code", DATA / "ai-code"),
        *[(path, HOMEBREW / "sce_sys" / path.name) for path in sorted((title / "sce_sys").iterdir())],
    ]
    if_new_size = [
        *files_under(data / "python", DATA / "python"),
        *files_under(arguments.soundtrack, DATA / "soundtrack"),
        (arguments.rom, DATA / "SOR.bin"),
        *files_under(title / "sce_module", HOMEBREW / "sce_module"),
        *files_under(title / "licenses", HOMEBREW / "licenses"),
    ]

    console = Console(arguments.host, arguments.port)

    # The title closes at launch without these, so a player should hear now, not then.
    for local, remote, advice in (
        (arguments.rom, DATA / "SOR.bin", "copy your ROM there, or pass --rom"),
        (arguments.soundtrack / "manifest.tsv", DATA / "soundtrack" / "manifest.tsv", "run scripts/render_soundtrack.py"),
    ):
        if not local.is_file() and console.size(remote) is None:
            print(f"{local} is missing, here and on the console: {advice}", file=sys.stderr)
            return 1
    if_new_size = [(local, remote) for local, remote in if_new_size if local.is_file()]

    to_send = list(always)
    for local, remote in if_new_size:
        if arguments.force or console.size(remote) != local.stat().st_size:
            to_send.append((local, remote))
    to_send.append((title / "eboot.bin", HOMEBREW / "eboot.bin"))

    total = sum(local.stat().st_size for local, _ in to_send)
    print(f"{len(to_send)} files, {total / 1_000_000:.1f} MB; {len(always) + len(if_new_size) + 1 - len(to_send)} already there")
    for index, (local, remote) in enumerate(to_send, 1):
        if arguments.dry_run:
            print(f"would send {remote} ({local.stat().st_size} bytes)")
            continue
        print(f"[{index}/{len(to_send)}] {remote}", flush=True)
        console.send(local, remote)
    console.ftp.quit()
    print("Nothing sent." if arguments.dry_run else "Done: launch the title from the home screen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
