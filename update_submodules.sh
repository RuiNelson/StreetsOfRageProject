#!/bin/bash
# Fetch and check out the latest configured branch of every submodule.

set -euo pipefail
cd "$(dirname "$0")"

git submodule sync --recursive
git submodule update --init --remote --recursive
git submodule status --recursive
