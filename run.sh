#!/bin/bash

# AI Rabbi - Run Script
# This script starts the AI Rabbi application

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}✡️  AI Rabbi - Torah Wisdom & Guidance${NC}"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
echo -e "${BLUE}Activating virtual environment...${NC}"
source venv/bin/activate

# Install dependencies
echo -e "${BLUE}Installing dependencies...${NC}"
pip install -q -r backend/requirements.txt

# Check for .env file
if [ ! -f "backend/.env" ]; then
    if [ -f "backend/.env.example" ]; then
        echo -e "${YELLOW}No .env file found. Creating from .env.example...${NC}"
        cp backend/.env.example backend/.env
        echo -e "${YELLOW}Please edit backend/.env and add your ANTHROPIC_API_KEY${NC}"
    fi
fi

# Start the server
echo ""
echo -e "${GREEN}Starting AI Rabbi server...${NC}"
echo -e "${BLUE}Open http://localhost:8000 in your browser${NC}"
echo ""

cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
