#!/usr/bin/env bash
# Build and run test_m68k_macros.cpp — unit tests for M68KMacros.hpp's ALU/CCR
# semantics (DESIGN.md §2b/§7). Standalone: no CMake target, no dependency on
# the rest of the build.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.."

bin="$(mktemp -t test_m68k_macros)"
trap 'rm -f "$bin"' EXIT
g++ -std=c++23 -Wall -Wextra \
    -I src -I src/system/cpu -I tools/recompiler \
    tools/recompiler/tests/test_m68k_macros.cpp -o "$bin"
"$bin"
