#!/bin/bash
set -e

# Run session server
exec python -m uvicorn py_code_mode.execution.container.server:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8080}" \
    --log-level info
