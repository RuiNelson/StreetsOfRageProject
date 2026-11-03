#!/usr/bin/env python3
"""Build the PS5 title in Docker into StreetsOfRageRecompilation/dist-ps5/. Touches neither build/ nor rom/."""

from __future__ import annotations

import argparse
import subprocess
import sys

from _common import META_ROOT

IMAGE = "sor-ps5-toolchain"
BUILD_VOLUME = "sor-ps5-build"  # the build tree: a bind mount is several times slower
RECOMPILATION = META_ROOT / "StreetsOfRageRecompilation"
DOCKER_CONTEXT = RECOMPILATION / "prospero" / "docker"
BUILD_SCRIPT = "/workspace/StreetsOfRageRecompilation/prospero/tools/build.sh"


def run_in_image(command: list[str], *, interactive: bool = False) -> int:
    arguments = ["docker", "run", "--rm"]
    if interactive:
        arguments.append("-it")
    arguments += ["-v", f"{META_ROOT}:/workspace", "-v", f"{BUILD_VOLUME}:/build", IMAGE, *command]
    return subprocess.call(arguments)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-cache", action="store_true", help="Rebuild every image layer")
    parser.add_argument("--image-only", action="store_true", help="Build and check the image, not the title")
    parser.add_argument("--clean", action="store_true", help="Empty the build volume first")
    parser.add_argument("--jobs", type=int, help="Parallel compile jobs (default: the container's CPUs)")
    parser.add_argument("--shell", action="store_true", help="Open a shell in the image afterwards")
    arguments = parser.parse_args()

    if not arguments.image_only and not (RECOMPILATION / "generated" / "SoR.hpp").exists():
        print("generated/ is missing: run scripts/generate_cpp.py --speculative first", file=sys.stderr)
        return 1

    build = ["docker", "build", "-t", IMAGE, str(DOCKER_CONTEXT)]
    if arguments.no_cache:
        build.insert(2, "--no-cache")
    if subprocess.call(build) != 0:
        return 1
    status = run_in_image(["bash", "/opt/ps5/check-toolchain.sh"])
    if status != 0:
        return status
    if arguments.clean:
        subprocess.call(["docker", "volume", "rm", "-f", BUILD_VOLUME])
    if not arguments.image_only:
        command = ["bash", BUILD_SCRIPT]
        if arguments.jobs:
            command.append(str(arguments.jobs))
        status = run_in_image(command)
        if status != 0:
            return status
    if arguments.shell:
        return run_in_image(["bash"], interactive=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
