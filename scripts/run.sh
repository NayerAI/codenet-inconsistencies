#!/usr/bin/env bash
# Convenience wrapper to run the framework either via Apptainer or natively.
#
#   scripts/run.sh <codenet-eval args...>
#
# The Apptainer image contains only the runtime; the framework CODE is read from
# this repo's ./src at run time, so editing code never needs an image rebuild.
# If codenet-eval.sif exists it is used; otherwise we run the local package.
# OPENROUTER_API_KEY is forwarded either way.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SIF="${CODENET_SIF:-codenet-eval.sif}"

if command -v apptainer >/dev/null 2>&1 && [[ -f "$SIF" ]]; then
    exec apptainer run \
        --bind "$REPO_ROOT" \
        --env "CODENET_EVAL_SRC=$REPO_ROOT/src" \
        --env "OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-}" \
        "$SIF" "$@"
else
    export PYTHONPATH="$REPO_ROOT/src:${PYTHONPATH:-}"
    exec python3 -m codenet_eval.cli "$@"
fi
