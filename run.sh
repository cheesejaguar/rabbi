#!/bin/bash

# rebbe.dev - Development Startup Script
# Checks for the uv package manager, creates .env from example if needed,
# installs dependencies, and launches the FastAPI server with hot-reload.

set -e  # Exit immediately if any command fails

# ANSI color codes for styled terminal output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}✡️  rebbe.dev - Torah Wisdom & Guidance${NC}"
echo ""

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo -e "${RED}uv is not installed. Please install it first:${NC}"
    echo -e "${YELLOW}curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
    exit 1
fi

# Install/update project dependencies from pyproject.toml and uv.lock
echo -e "${BLUE}Syncing dependencies with uv...${NC}"
uv sync

# Check for .env file
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo -e "${YELLOW}No .env file found. Creating from .env.example...${NC}"
        cp .env.example .env
        echo -e "${YELLOW}Please edit .env and add your API keys${NC}"
    fi
fi

# Start the server
echo ""
echo -e "${GREEN}Starting rebbe.dev server...${NC}"
echo -e "${BLUE}Open http://localhost:8000 in your browser${NC}"
echo ""

# Launch uvicorn via uv (ensures the project venv is used).
# --reload watches for file changes and restarts the server automatically.
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
