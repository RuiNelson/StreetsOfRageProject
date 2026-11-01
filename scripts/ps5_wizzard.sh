#!/bin/bash
# Build Streets of Rage for the PlayStation 5 on macOS or Linux, step by step, with nothing to
# install but a container engine (Docker, OrbStack, Podman). Run it from a terminal:
#
#   ./scripts/ps5_wizzard.sh
#
# The ZIP files it makes go to the folder you run it from. The steps are in scripts/ps5_wizard/:
# tui.sh (the screen), steps.sh (the work), and macos.sh or linux.sh (what differs).

SCRIPTS_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$SCRIPTS_DIR/ps5_wizard/tui.sh"
. "$SCRIPTS_DIR/ps5_wizard/steps.sh"

case "$(uname -s)" in
    Darwin) . "$SCRIPTS_DIR/ps5_wizard/macos.sh" ;;
    Linux) . "$SCRIPTS_DIR/ps5_wizard/linux.sh" ;;
    *)
        echo "This wizard runs on macOS and Linux." >&2
        exit 1
        ;;
esac

wizard_main
