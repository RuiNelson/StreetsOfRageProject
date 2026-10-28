#!/usr/bin/env python3
"""Build the soundtrack renderer and pre-render every music track, sound effect
and PCM voice to FLAC for `sor --sound prerendered` (the default).

The renderer (StreetsOfRageRecompilation/tools/soundtrack) runs the ROM's own
sound engine on Genesis Plus GX with the Nuked OPN2 core, so the output is
derived from the copyrighted ROM: it goes next to the ROM and is never versioned.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from _common import META_ROOT, absolute_path, built_executable


def main() -> int:
    sor_root = META_ROOT / "StreetsOfRageRecompilation"
    tool_root = sor_root / "tools" / "soundtrack"
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rom", default=os.environ.get("SOR_ROM", sor_root / "rom" / "SOR.bin"),
                        help="ROM to render from (default: $SOR_ROM or rom/SOR.bin)")
    parser.add_argument("--out", help="output directory (default: soundtrack/ next to the ROM, where sor looks)")
    parser.add_argument("--chip", choices=("ym3438", "ym2612"), default="ym3438",
                        help="Nuked OPN2 chip model (default: ym3438)")
    parser.add_argument("--clean", action="store_true", help="rebuild the renderer from scratch")
    parser.add_argument("--jobs", default=str(os.cpu_count() or 4), help="parallel build jobs")
    arguments = parser.parse_args()

    rom = absolute_path(arguments.rom)
    if not rom.is_file():
        print(f"ROM not found: {rom}", file=sys.stderr)
        return 1
    out = absolute_path(arguments.out) if arguments.out else rom.parent / "soundtrack"

    build_dir = tool_root / "build"
    if arguments.clean and build_dir.exists():
        shutil.rmtree(build_dir)
    if not (build_dir / "CMakeCache.txt").is_file():
        subprocess.run(["cmake", "-S", str(tool_root), "-B", str(build_dir), "-DCMAKE_BUILD_TYPE=Release"], check=True)
    command = ["cmake", "--build", str(build_dir), "--parallel", arguments.jobs]
    if "CMAKE_CONFIGURATION_TYPES:" in (build_dir / "CMakeCache.txt").read_text(errors="replace"):
        command.extend(["--config", "Release"])
    subprocess.run(command, check=True)

    # Render into a fresh directory and swap it in, so a failed run never
    # leaves a half-written soundtrack where sor would pick it up.
    staging = out.with_name(out.name + ".rendering")
    shutil.rmtree(staging, ignore_errors=True)
    renderer = built_executable(build_dir, "sor_soundtrack")
    print(f"==> Rendering {rom} -> {out}", flush=True)
    status = subprocess.run([str(renderer), "--rom", str(rom), "--out", str(staging), "--chip", arguments.chip]).returncode
    if status != 0:
        print(f"Rendering failed ({status}); {out} left unchanged, partial output in {staging}", file=sys.stderr)
        return status
    shutil.rmtree(out, ignore_errors=True)
    staging.rename(out)
    print(f"==> Done: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
