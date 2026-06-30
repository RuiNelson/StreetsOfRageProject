#!/bin/bash
# Iteratively discover the jump-table targets that static analysis misses.
#
# Each run of the recompiled cartridge with --auxAddrFile appends the first
# unknown indirect-dispatch target it hits to aux_addresses.txt and exits 42.
# We then regenerate + rebuild (build.sh --full) and run again, converging on
# exactly the addresses the game actually executes — conservative, no heuristics.
#
# Stops when:
#   * a run hits an address already in the aux file (exit 43)     -> a seeded
#       address still produced no handler: a genuine bad index / state bug to
#       investigate by hand, not a missing entry point. Stops (1).
#   * the build or the run fails some other way                   -> stops.
#   * the user kills the process (Ctrl+C / SIGTERM)               -> stops.
#
# Usage:
#   ./discover_aux.sh                 Run the loop with the defaults below.
# Env overrides:
#   MAX_ITERS=500    safety cap on iterations
#   SOR_ROM=rom/SOR.bin

set -uo pipefail
cd "$(dirname "$0")"

AUX="code-analysis/aux_addresses.txt"
ROM="${SOR_ROM:-rom/SOR.bin}"
BIN="src/build/sor"
MAX_ITERS="${MAX_ITERS:-500}"
BUILD_LOG="$(mktemp -t discover_build.XXXXXX)"
trap 'rm -f "$BUILD_LOG"' EXIT

start_count=$(grep -cE '^[0-9a-fA-F]+' "$AUX")

for ((i = 1; i <= MAX_ITERS; i++)); do
    pkill -9 -f "$BIN" 2>/dev/null

    echo "==> [discover $i] regenerate + build (--full)"
    if ! ./build.sh --full >"$BUILD_LOG" 2>&1; then
        echo "Build failed:" >&2
        tail -25 "$BUILD_LOG" >&2
        exit 1
    fi

    echo "==> [discover $i] run"
    "$BIN" --runSor --fast \
        --auxAddrFile "$AUX" --rom "$ROM" 2>&1 | grep -E '\[aux\]|unknown address'
    code=${PIPESTATUS[0]}

    case "$code" in
        42)
            echo "==> [discover $i] recorded a new address; re-seeding"
            ;;
        43)
            echo "==> [discover $i] STUCK: a seeded address still has no handler —" >&2
            echo "    likely a bad jump-table index (state bug), not a missing entry." >&2
            exit 1
            ;;
        *)
            echo "==> [discover $i] exited $code (not an unknown dispatch). Stopping." >&2
            exit "$code"
            ;;
    esac
done

echo "Reached MAX_ITERS=$MAX_ITERS without converging." >&2
exit 1
