#!/usr/bin/env bash
# ─────────────────────────────────────────────
# Beats Backend — Startup Script (Fedora 42)
# Usage: bash run.sh
# ─────────────────────────────────────────────

set -e

VENV_DIR=".venv"
DATA_DIR="data/models"

echo "🎵 Beats Backend Setup"
echo "─────────────────────"

# 1. Create virtualenv if not exists
if [ ! -d "$VENV_DIR" ]; then
  echo "→ Creating Python virtual environment..."
  python3 -m venv $VENV_DIR
fi

# 2. Install deps
echo "→ Installing dependencies..."
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

# 3. Create data dirs
mkdir -p $DATA_DIR data/features

# 4. Copy env if not exists
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "→ Created .env from .env.example"
fi

# 5. Run
echo ""
echo "✅ Starting Beats API on http://localhost:8000"
echo "   Docs:      http://localhost:8000/docs"
echo "   ML status: http://localhost:8000/api/ml/status"
echo ""

.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
