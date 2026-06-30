#!/bin/bash
# Run the Streets of Rage disassembler with auxiliary addresses.

set -e

ROM="${1:-rom/SOR.bin}"
AUX="code-analysis/aux_addresses.txt"
ADDR_CSV="code-analysis/addresses.csv"
BLOCKS_CSV="code-analysis/blocks.csv"
LABELS_CSV="code-analysis/labels.csv"
OUT_DIR="output"

mkdir -p "$OUT_DIR"

python3 -m tools.disassembler "$ROM" \
    -o "$OUT_DIR/sor.asm" \
    -a "$AUX" \
    --addresses-csv "$ADDR_CSV" \
    --blocks-csv "$BLOCKS_CSV" \
    --labels-csv "$LABELS_CSV" \
    --map "$OUT_DIR/sor.map" \
    -v
