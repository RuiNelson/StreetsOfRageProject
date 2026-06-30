#!/bin/bash
# Smart build for the C++ recompilation (the `sor` target).
#
# - Configures only when needed (no build dir, or CMakeLists.txt changed).
# - Auto-detects the CPU count for a parallel build.
# - Recovers automatically from the known libpng dependency breakage by
#   re-fetching libpng and retrying once.
# - Optionally runs the built binary afterwards.
#
# Usage:
#   ./build.sh                     Configure (if needed) and build.
#   ./build.sh -f | --full         Recompile the ROM to C++ (run the recompiler)
#                                  before building. ROM: $SOR_ROM or rom/SOR.bin.
#   ./build.sh -d | --discover     With --full: also pass speculative_addresses.txt
#                                  to the recompiler (for discover_aux_fast.sh runs).
#                                  Omit for normal builds — no speculative stubs.
#   ./build.sh -c | --clean        Wipe the build dir and reconfigure from scratch.
#   ./build.sh -t Release          Set the CMake build type (default: Debug).
#   ./build.sh -j 8                Override the parallel job count.
#   ./build.sh -r  [args...]        Build, then run `sor` with the remaining args.
#   ./build.sh --run -- --testVDP   Same; everything after -r/--run goes to `sor`.
#   ./build.sh -h | --help          Show this help.
#
# Examples:
#   ./build.sh --clean
#   ./build.sh --full              Regenerate src/generated from the ROM, then build.
#   ./build.sh -r --testVDP
#   ./build.sh -t Release -r --testControllers

set -uo pipefail

# Run relative to the repository root (the script's directory) so the paths
# below work no matter where the script is invoked from.
ORIG_PWD="$PWD"
cd "$(dirname "$0")"
ROOT="$PWD"

SRC_DIR="src"
BUILD_DIR="src/build"
BIN="$ROOT/$BUILD_DIR/sor"

BUILD_TYPE="Debug"
CLEAN=0
FULL=0
DISCOVER=0
RUN=0
RUN_ARGS=()
JOBS=""

usage() {
    # Print the leading comment block (after the shebang), stripping the "# ".
    awk 'NR==1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
    exit "${1:-0}"
}

# ── Parse arguments ────────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        -c | --clean) CLEAN=1 ;;
        -f | --full) FULL=1 ;;
        -d | --discover) DISCOVER=1 ;;
        -t | --type)
            shift
            BUILD_TYPE="${1:?missing build type after -t}"
            ;;
        -j | --jobs)
            shift
            JOBS="${1:?missing job count after -j}"
            ;;
        -r | --run)
            RUN=1
            shift
            # Everything after -r/--run is passed to the binary. Drop a lone
            # "--" separator if present.
            [ "${1:-}" = "--" ] && shift
            RUN_ARGS=("$@")
            break
            ;;
        -h | --help) usage 0 ;;
        *)
            echo "Unknown option: $1" >&2
            usage 1
            ;;
    esac
    shift
done

# ── Detect parallel job count ──────────────────────────────────────────────────
if [ -z "$JOBS" ]; then
    if command -v nproc >/dev/null 2>&1; then
        JOBS="$(nproc)"
    elif command -v sysctl >/dev/null 2>&1; then
        JOBS="$(sysctl -n hw.ncpu 2>/dev/null || echo 4)"
    else
        JOBS=4
    fi
fi

# ── Full: recompile the ROM to C++ ──────────────────────────────────────────────
# Runs the recursive-descent recompiler (tools/recompiler) to regenerate
# src/generated/Sor.{hpp,cpp} from the ROM. Normal --full builds use only
# aux_addresses.txt; --full --discover additionally compiles speculative
# candidates as temporary discovery hooks. The regenerated sources are then
# built below.
if [ "$FULL" = 1 ]; then
    ROM="${SOR_ROM:-rom/SOR.bin}"
    if [ ! -f "$ROM" ]; then
        echo "Full build: ROM not found at '$ROM' (set \$SOR_ROM to override)." >&2
        exit 1
    fi
    echo "==> Full: recompiling $ROM -> $SRC_DIR/generated"
    SPEC_ARG=""
    if [ "$DISCOVER" = 1 ]; then
        SPEC_FILE="code-analysis/speculative_addresses.txt"
        [ -f "$SPEC_FILE" ] && SPEC_ARG="--speculative $SPEC_FILE"
    fi
    # shellcheck disable=SC2086
    if ! python3 -m tools.recompiler "$ROM" -o "$SRC_DIR/generated" $SPEC_ARG; then
        echo "Recompile failed." >&2
        exit 1
    fi
fi

# ── Configure ──────────────────────────────────────────────────────────────────
if [ "$CLEAN" = 1 ]; then
    echo "==> Clean: removing $BUILD_DIR"
    rm -rf "$BUILD_DIR"
fi

need_configure() {
    [ ! -f "$BUILD_DIR/CMakeCache.txt" ] && return 0
    [ "$SRC_DIR/CMakeLists.txt" -nt "$BUILD_DIR/CMakeCache.txt" ] && return 0
    return 1
}

if need_configure; then
    echo "==> Configuring ($BUILD_TYPE)"
    if ! cmake -S "$SRC_DIR" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE="$BUILD_TYPE"; then
        echo "Configure failed. If this is an SDK/header error, try a clean build:" >&2
        echo "  ./build.sh --clean" >&2
        exit 1
    fi
fi

# ── Build (with one-shot libpng recovery) ──────────────────────────────────────
LOG="$(mktemp -t sor_build.XXXXXX)"
trap 'rm -f "$LOG"' EXIT

build_once() {
    cmake --build "$BUILD_DIR" -j "$JOBS" 2>&1 | tee "$LOG"
    return "${PIPESTATUS[0]}"
}

echo "==> Building sor (-j $JOBS)"
if ! build_once; then
    if grep -qiE "png_xy|png_framework|png_shared|libpng-src.*error" "$LOG"; then
        echo "==> libpng dependency looks broken — re-fetching it and retrying once."
        rm -rf "$BUILD_DIR/_deps/libpng-src" \
            "$BUILD_DIR/_deps/libpng-build" \
            "$BUILD_DIR/_deps/libpng-subbuild"
        if ! build_once; then
            echo "Build failed after libpng recovery." >&2
            exit 1
        fi
    else
        echo "Build failed." >&2
        exit 1
    fi
fi

echo "==> Built: $BIN"

# ── Optionally run ──────────────────────────────────────────────────────────────
if [ "$RUN" = 1 ]; then
    echo "==> Running: sor ${RUN_ARGS[*]}"
    # Run from the directory the user invoked the script in, so any output files
    # (e.g. the VDP test PNGs) land there rather than in the repo root.
    cd "$ORIG_PWD"
    exec "$BIN" "${RUN_ARGS[@]}"
fi
