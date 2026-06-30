#!/bin/bash
# Fast aux discovery: speculate → build → loop.
#
# 1. Scan unmapped ROM regions for 68000 entry point candidates (speculative_scan.py)
#    and write them to code-analysis/speculative_addresses.txt.
# 2. Build once with all speculative stubs compiled in (--full --discover).
# 3. Run the game in a loop:
#      - Confirmed speculative addresses are appended to aux_addresses.txt on-the-fly
#        (no restart needed for those).
#      - Unknown non-speculative addresses exit 42: add to aux, rebuild, run again.
#      - exit 43 (stuck address): genuine state bug, stop.
#      - Ctrl+C or any other exit: stop.
#
# Compared to discover_aux.sh: fewer rebuild iterations because speculative stubs
# cover many jump-table targets that would otherwise each require a rebuild.
#
# Usage:
#   ./discover_aux_fast.sh
# Env overrides:
#   SOR_ROM=rom/SOR.bin
#   MAX_ITERS=500

set -uo pipefail
cd "$(dirname "$0")"

AUX="code-analysis/aux_addresses.txt"
SPEC="code-analysis/speculative_addresses.txt"
ROM="${SOR_ROM:-rom/SOR.bin}"
BIN="src/build/sor"
MAX_ITERS="${MAX_ITERS:-500}"
SCAN_ASM="$(mktemp -t sor_fast_disasm.XXXXXX)"
SCAN_MAP="$(mktemp -t sor_fast_map.XXXXXX)"
trap 'rm -f "$SCAN_ASM" "$SCAN_MAP"' EXIT

start_count=$(grep -cE '^[0-9a-fA-F]+' "$AUX" 2>/dev/null || echo 0)

echo "==> [fast] Refreshing coverage map from current aux addresses..."
if ! python3 -m tools.disassembler "$ROM" -o "$SCAN_ASM" -a "$AUX" --map "$SCAN_MAP"; then
    echo "Coverage-map refresh failed." >&2
    exit 1
fi

echo "==> [fast] Scanning for speculative entry points..."
if ! python3 -m tools.speculative_scan "$SCAN_MAP" "$ROM" "$AUX" -o "$SPEC"; then
    echo "Speculative scan failed." >&2
    exit 1
fi
spec_count=$(grep -cE '^[0-9a-fA-F]+' "$SPEC" 2>/dev/null || echo 0)
echo "    $spec_count speculative candidates written to $SPEC"

do_build() {
    echo "==> [fast $1] build (--full --discover)"
    if ! ./build.sh --full --discover; then
        echo "Build failed." >&2
        exit 1
    fi
}

do_build "init"

for ((i = 1; i <= MAX_ITERS; i++)); do
    pkill -9 -f "$BIN" 2>/dev/null

    echo "==> [fast $i] run"
    "$BIN" --runSor --fast --rom "$ROM" \
        --auxAddrFile "$AUX" 2>&1 | grep -E '\[speculative\]|\[aux\]|unknown address'
    code=${PIPESTATUS[0]}

    case "$code" in
        42)
            echo "==> [fast $i] new unknown address recorded; rebuilding"
            do_build "$i"
            ;;
        43)
            echo "==> [fast $i] STUCK: a seeded address still has no handler —" >&2
            echo "    likely a bad jump-table index (state bug), not a missing entry." >&2
            exit 1
            ;;
        *)
            now=$(grep -cE '^[0-9a-fA-F]+' "$AUX" 2>/dev/null || echo 0)
            echo "==> [fast $i] exited $code. Added $((now - start_count)) address(es) over $i iteration(s)."
            exit 0
            ;;
    esac
done

echo "Reached MAX_ITERS=$MAX_ITERS without converging." >&2
exit 1
