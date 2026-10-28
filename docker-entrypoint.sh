#!/bin/bash
set -e

# Copy baked seed artifacts from /app/seed into writable dirs (only if empty).
# This allows the Docker image to contain a snapshot of data/models/outputs
# so the mentor sees a populated dashboard on first run.
if [ -d /app/seed ]; then
    for sub in data/raw data/processed data/labels data/synthetic outputs models config; do
        if [ -d "/app/seed/$sub" ]; then
            cp -rn /app/seed/$sub/. /app/$sub/ 2>/dev/null || true
        fi
    done
fi

echo "[entrypoint] Starting Streamlit on port 8501..."
exec streamlit run app.py --server.port 8501 --server.address 0.0.0.0