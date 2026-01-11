#!/bin/bash

# rebbe.dev - Run Script
# This script starts the rebbe.dev application

set -e

# Colors for output
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

# Sync dependencies
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

uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
