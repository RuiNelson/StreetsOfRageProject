#!/bin/bash
# Iterative disassembler loop for Streets of Rage.

set -e

ROM="${1:-rom/SOR.bin}"
OUT_DIR="output"
SOR_ASM="${OUT_DIR}/sor.asm"
SOR_MAP="${OUT_DIR}/sor.map"
EXODUS="etc/sor-exodus.asm"
AUX="aux_addresses.txt"

mkdir -p "$OUT_DIR"

# First pass: disassemble with current aux_addresses
python3 -m tools.disassembler "$ROM" \
    -o "$SOR_ASM" \
    -a "$AUX" \
    --map "$SOR_MAP" \
    -v

# Iterative loop: add missing addresses one by one
python3 tools/iterative_disasm/script.py \
    "$SOR_ASM" \
    "$SOR_MAP" \
    "$EXODUS" \
    "$AUX" \
    "$ROM"
