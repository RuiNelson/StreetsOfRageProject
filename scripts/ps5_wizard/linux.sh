#!/bin/bash
# What differs on Linux for scripts/ps5_wizzard.sh. Sourced, not run.

# The containers run as root, so the files they write need handing back to the user. A rootless
# engine (rootless Podman or Docker) already writes them as the user, and SELinux needs the
# workspace relabelled for the container to read it.
if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce 2>/dev/null)" = Enforcing ]; then
    DOCKER_WORKSPACE_OPTIONS=":z"
fi

platform_engine_options() {
    echo "Docker Engine|https://docs.docker.com/engine/install/|Free. Packages for Ubuntu, Debian, Fedora and others."
    echo "Podman|https://podman.io/docs/installation|Free. In most distributions' repositories; install podman-docker for the docker command."
}

platform_engine_start_hint() {
    echo "Start the service: sudo systemctl enable --now docker (or: systemctl --user start podman.socket)."
    echo "If it says permission denied, add yourself to the docker group, then log out and in again: sudo usermod -aG docker \$USER"
}

platform_tools_hint() {
    if command -v apt-get >/dev/null 2>&1; then
        echo "Install them with: sudo apt-get install curl zip"
    elif command -v dnf >/dev/null 2>&1; then
        echo "Install them with: sudo dnf install curl zip"
    elif command -v pacman >/dev/null 2>&1; then
        echo "Install them with: sudo pacman -S curl zip"
    elif command -v zypper >/dev/null 2>&1; then
        echo "Install them with: sudo zypper install curl zip"
    else
        echo "Install them with your distribution's package manager (the packages are usually called curl and zip)."
    fi
}

platform_open_url() {
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$1" >/dev/null 2>&1 &
    else
        printf '  Open this address in your browser: %s\n' "$1"
        sleep 2
    fi
}

platform_sha256() { sha256sum "$1" | awk '{ print $1 }'; }

platform_pick_file() {
    if command -v zenity >/dev/null 2>&1; then
        zenity --file-selection --title="Choose your Streets of Rage ROM (Mega Drive / Genesis, JUE Rev. A)" 2>/dev/null
    elif command -v kdialog >/dev/null 2>&1; then
        kdialog --getopenfilename "$HOME" 2>/dev/null
    else
        return 1
    fi
}

platform_fix_ownership() {
    if docker info --format '{{.SecurityOptions}}' 2>/dev/null | grep -qi rootless; then
        return 0
    fi
    local sor=/workspace/StreetsOfRageRecompilation
    run_task "Giving you the files the container made" docker_run sh -c "
        for path in $sor/generated $sor/dist-ps5 $sor/rom/soundtrack; do
            [ -e \"\$path\" ] && chown -R $(id -u):$(id -g) \"\$path\"
        done
        true"
}
