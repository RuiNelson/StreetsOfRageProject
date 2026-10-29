#!/usr/bin/env python3
"""Configure and build the Streets of Rage host with only stdlib tooling."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from _common import META_ROOT, absolute_path, cmake_configure_arguments, executable_path, prepend_pythonpath


def usage() -> None:
    print(f"Usage: {Path(sys.argv[0]).name} [--release] [--full] [--discover] [--clean] [--jobs N] [--run [sor options...]]")
    print("\n  --release       Clean and build the Release configuration.")
    print("  --full          Regenerate C++ from the ROM before building.")
    print("  --discover      Include speculative entry points with --full.")
    print("  --clean         Remove the build directory before configuring.")
    print("  --jobs N        Override the parallel build job count.")
    print("  --run           Run sor after building; remaining arguments go to sor.")


def parse_arguments(arguments: list[str]) -> tuple[str, bool, bool, bool, list[str], str | None]:
    build_type, full, discover, clean = "Debug", False, False, False
    jobs: str | None = None
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--release":
            build_type, clean = "Release", True
        elif argument in {"-c", "--clean"}:
            clean = True
        elif argument in {"-f", "--full"}:
            full = True
        elif argument in {"-d", "--discover"}:
            discover = True
        elif argument in {"-t", "--type", "-j", "--jobs"}:
            if index + 1 == len(arguments):
                raise ValueError(f"Missing value after {argument}")
            value = arguments[index + 1]
            if argument in {"-t", "--type"}:
                build_type = value
            else:
                jobs = value
            index += 1
        elif argument in {"-r", "--run"}:
            return build_type, full, discover, clean, arguments[index + 1 :], jobs
        elif argument in {"-h", "--help"}:
            usage()
            raise SystemExit(0)
        else:
            raise ValueError(f"Unknown option: {argument}")
        index += 1
    return build_type, full, discover, clean, [], jobs


def run_full_generation(sor_root: Path, decompiler: Path, discover: bool) -> None:
    rom = absolute_path(os.environ.get("SOR_ROM", sor_root / "rom" / "SOR.bin"))
    if not rom.is_file():
        raise RuntimeError(f"Full build: ROM not found at '{rom}' (set SOR_ROM to override).")
    command = [
        sys.executable,
        "-m",
        "tools",
        "recompile",
        str(rom),
        "-o",
        str(sor_root / "generated"),
        "--aux",
        str(sor_root / "code-analysis" / "aux_addresses.txt"),
        "--labels-csv",
        str(sor_root / "code-analysis" / "labels.csv"),
        "--addresses-csv",
        str(sor_root / "code-analysis" / "addresses.csv"),
        "--manual-functions",
        str(sor_root / "code-analysis" / "manual_functions.txt"),
    ]
    speculative = sor_root / "code-analysis" / "speculative_addresses.txt"
    if discover and speculative.is_file():
        command.extend(["--speculative", str(speculative)])
    environment = os.environ.copy()
    prepend_pythonpath(environment, decompiler)
    print(f"==> Full: recompiling {rom} -> generated")
    subprocess.run(command, check=True, env=environment)


def needs_configure(build_dir: Path, source_paths: list[Path]) -> bool:
    cache = build_dir / "CMakeCache.txt"
    return not cache.is_file() or any(path.stat().st_mtime > cache.stat().st_mtime for path in source_paths)


def build(command: list[str], build_dir: Path) -> tuple[int, str]:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    output: list[str] = []
    for line in process.stdout:
        print(line, end="")
        output.append(line)
    return process.wait(), "".join(output)


def main() -> int:
    try:
        build_type, full, discover, clean, run_arguments, jobs = parse_arguments(sys.argv[1:])
        sor_root = META_ROOT / "StreetsOfRageRecompilation"
        build_dir = sor_root / "build"
        if full:
            run_full_generation(sor_root, META_ROOT / "RageDecompiler", discover)
        if clean and build_dir.exists():
            print(f"==> Clean: removing {build_dir}")
            shutil.rmtree(build_dir)
        if needs_configure(build_dir, [sor_root / "CMakeLists.txt", META_ROOT / "MegaDriveEnvironment" / "CMakeLists.txt"]):
            print(f"==> Configuring ({build_type})")
            configure_command = ["cmake", "-S", str(sor_root), "-B", str(build_dir), f"-DCMAKE_BUILD_TYPE={build_type}",
                                 *cmake_configure_arguments(build_dir)]
            toolchain = os.environ.get("CMAKE_TOOLCHAIN_FILE")
            if toolchain:
                configure_command.append(f"-DCMAKE_TOOLCHAIN_FILE={toolchain}")
            subprocess.run(configure_command, check=True)
        jobs = jobs or str(os.cpu_count() or 4)
        command = ["cmake", "--build", str(build_dir), "--parallel", jobs]
        cache_text = (build_dir / "CMakeCache.txt").read_text(errors="replace")
        if "CMAKE_CONFIGURATION_TYPES:" in cache_text:
            command.extend(["--config", build_type])
        print(f"==> Building sor (--parallel {jobs})")
        status, output = build(command, build_dir)
        if status:
            if any(term in output.lower() for term in ("png_xy", "png_framework", "png_shared", "libpng-src")):
                print("==> libpng dependency looks broken — re-fetching it and retrying once.")
                for path in ("libpng-src", "libpng-build", "libpng-subbuild"):
                    shutil.rmtree(build_dir / "_deps" / path, ignore_errors=True)
                status, _ = build(command, build_dir)
            if status:
                return status
        executable = executable_path(build_dir / build_type if "CMAKE_CONFIGURATION_TYPES:" in cache_text else build_dir, "sor")
        print(f"==> Built: {executable}")
        if run_arguments:
            return subprocess.run([str(executable), *run_arguments]).returncode
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
