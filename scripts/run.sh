#!/usr/bin/env bash
# Convenience wrapper to run the framework either natively or via Apptainer.
#
#   scripts/run.sh <codenet-eval args...>
#
# If codenet-eval.sif exists it is used; otherwise the local Python package is
# invoked (pip install -e . first). The OPENROUTER_API_KEY env var is forwarded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SIF="${CODENET_SIF:-codenet-eval.sif}"

if command -v apptainer >/dev/null 2>&1 && [[ -f "$SIF" ]]; then
    exec apptainer run \
        --bind "$PWD/data:$PWD/data" \
        --env "OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-}" \
        "$SIF" "$@"
else
    export PYTHONPATH="$REPO_ROOT/src:${PYTHONPATH:-}"
    exec python3 -m codenet_eval.cli "$@"
fi
