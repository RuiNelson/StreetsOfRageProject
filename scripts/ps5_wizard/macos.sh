#!/bin/bash
# What differs on macOS for scripts/ps5_wizzard.sh. Sourced, not run.

platform_engine_options() {
    echo "Docker Desktop|https://www.docker.com/products/docker-desktop/|Free, with paid plans."
    echo "Podman Desktop|https://podman-desktop.io/|Free."
    echo "OrbStack|https://orbstack.dev/|Free for personal use. Recommended for macOS users."
}

platform_engine_start_hint() {
    echo "Open Docker Desktop or OrbStack and wait until it says it is running. With Podman Desktop, start the Podman machine."
}

platform_tools_hint() {
    echo "They come with macOS: this installation looks damaged."
}

platform_open_url() { open "$1"; }

platform_sha256() { shasum -a 256 "$1" | awk '{ print $1 }'; }

platform_pick_file() {
    osascript -e 'POSIX path of (choose file with prompt "Choose your Streets of Rage ROM (Mega Drive / Genesis, JUE Rev. A)")' 2>/dev/null
}
