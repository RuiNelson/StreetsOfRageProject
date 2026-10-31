#!/usr/bin/env python3
"""Build the PS5 toolchain image and check it. Needs Docker; touches neither build/ nor rom/."""

from __future__ import annotations

import argparse
import subprocess
import sys

from _common import META_ROOT

IMAGE = "sor-ps5-toolchain"
BUILD_VOLUME = "sor-ps5-build"  # the build tree: a bind mount is several times slower
DOCKER_CONTEXT = META_ROOT / "StreetsOfRageRecompilation" / "prospero" / "docker"


def run_in_image(command: list[str], *, interactive: bool = False) -> int:
    arguments = ["docker", "run", "--rm"]
    if interactive:
        arguments.append("-it")
    arguments += ["-v", f"{META_ROOT}:/workspace", "-v", f"{BUILD_VOLUME}:/build", IMAGE, *command]
    return subprocess.call(arguments)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-cache", action="store_true", help="Rebuild every image layer")
    parser.add_argument("--shell", action="store_true", help="Open a shell in the image afterwards")
    arguments = parser.parse_args()

    build = ["docker", "build", "-t", IMAGE, str(DOCKER_CONTEXT)]
    if arguments.no_cache:
        build.insert(2, "--no-cache")
    if subprocess.call(build) != 0:
        return 1
    status = run_in_image(["bash", "/opt/ps5/check-toolchain.sh"])
    if status != 0:
        return status
    if arguments.shell:
        return run_in_image(["bash"], interactive=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
