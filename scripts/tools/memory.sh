#!/usr/bin/env bash
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
set -euo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export RELAX_MEMORY_STATE="${RELAX_MEMORY_STATE:-${XDG_STATE_HOME:-${HOME}/.local/state}/relax-memory}"
PYTHON="${MEMORY_PYTHON:-python}"
MEMORY_ENDPOINT="${RELAX_MEMORY_ENDPOINT:-http://127.0.0.1:${RELAX_MEMORY_PORT:-8765}}"

case "${1:-help}" in
    remote)
        shift
        exec "${PYTHON}" "${ROOT}/scripts/tools/memory_remote/client.py" "$@"
        ;;
    up|local)
        "${PYTHON}" -m relax.memory init --state-dir "${RELAX_MEMORY_STATE}"
        exec "${PYTHON}" -m relax.memory serve --state-dir "${RELAX_MEMORY_STATE}" --host "${RELAX_MEMORY_HOST:-127.0.0.1}" --port "${RELAX_MEMORY_PORT:-8765}"
        ;;
    verify|verify-memos)
        verify_args=(--endpoint "${MEMORY_ENDPOINT}" --admin-file "${RELAX_MEMORY_STATE}/admin.json")
        if [[ "$1" == "verify-memos" ]]; then
            [[ -n "${MEMOS_ENDPOINT:-}" ]] || { echo "Set MEMOS_ENDPOINT to an existing MemOS self-hosted API; this script does not deploy MemOS." >&2; exit 1; }
            verify_args+=(--memos-endpoint "${MEMOS_ENDPOINT}")
        fi
        exec "${PYTHON}" "${ROOT}/examples/memory/verify.py" "${verify_args[@]}"
        ;;
    status)
        exec "${PYTHON}" -c 'import json,sys,urllib.request; response=urllib.request.urlopen(sys.argv[1].rstrip("/")+"/health", timeout=5); data=json.load(response); assert data.get("service")=="relax-memory", "Unexpected service"; sys.stdout.write(json.dumps(data)+"\n")' "${MEMORY_ENDPOINT}"
        ;;
    help|-h|--help)
        echo "Usage: bash scripts/tools/memory.sh {up|local|verify|verify-memos|status|remote}"
        echo "up/local runs in the foreground. Stop with Ctrl-C; data is retained."
        ;;
    *)
        echo "Unsupported command: $1. Use up/local to start, status to check, and Ctrl-C to stop." >&2
        exit 2
        ;;
esac
