#!/bin/bash
# Louise — one-command setup and launch
# Usage: bash setup.sh
set -e

echo "=== Louise Safety Drone System ==="
echo ""

# Check .env
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "Created .env from .env.example — edit it to add your API keys:"
    echo "  MISTRAL_API_KEY=..."
    echo "  FLYSTRAL_ENDPOINT=...  (from flystral/serve_colab.ipynb on Colab)"
    echo "  HELPSTRAL_ENDPOINT=... (from helpstral/serve_colab.ipynb on Colab)"
    echo ""
fi

# Python install
if command -v docker &>/dev/null && [ "${USE_DOCKER:-0}" = "1" ]; then
    echo "[Docker] Building and starting Louise..."
    docker compose up --build
else
    echo "[Python] Installing dependencies..."
    pip install -r requirements.txt -q

    echo "[Server] Starting Louise on http://localhost:8000"
    echo ""
    echo "  User app:       http://localhost:8000/user"
    echo "  Mission control: http://localhost:8000/partner"
    echo ""
    echo "  To start SITL (ArduPilot): bash start_sitl.sh"
    echo "  To start camera feed:      python autopilot_adapter/camera_stream.py --server http://localhost:8000"
    echo ""
    uvicorn server:app --reload --host 0.0.0.0 --port 8000
fi
