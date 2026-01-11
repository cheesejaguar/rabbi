# AI Rabbi

A multi-agent AI system for exploring Jewish thought, practice, and meaning from a progressive Modern Orthodox perspective.

[![Tests](https://github.com/cheesejaguar/rabbi/actions/workflows/tests.yml/badge.svg)](https://github.com/cheesejaguar/rabbi/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

## Overview

AI Rabbi is a chatbot that provides guidance on questions of Jewish law, ethics, and spirituality. It uses a multi-agent architecture where specialized agents handle different aspects of rabbinic reasoning:

- **Pastoral Context Agent** - Determines *how* to respond based on emotional context
- **Halachic Reasoning Agent** - Provides the landscape of Jewish legal opinions
- **Moral-Ethical Agent** - Ensures responses preserve human dignity
- **Meta-Rabbinic Voice Agent** - Crafts the final response with appropriate tone

**Important:** This is guidance, not binding psak (legal ruling). A rabbi who knows you personally may counsel differently.

## Features

- Real-time streaming responses
- WorkOS SSO authentication
- Mobile-friendly dark theme UI
- Multi-agent reasoning pipeline
- Token-by-token response streaming

## Quick Start

### Prerequisites

- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) package manager
- An [OpenRouter](https://openrouter.ai/) API key

### Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/cheesejaguar/rabbi.git
   cd rabbi
   ```

2. **Install uv** (if not already installed)

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **Install dependencies**

   ```bash
   uv sync
   ```

4. **Configure environment variables**

   ```bash
   cp .env.example .env
   ```

   Edit `.env` and add your API keys:

   ```bash
   OPENROUTER_API_KEY=your-openrouter-api-key

   # Optional: WorkOS for authentication
   WORKOS_API_KEY=your-workos-api-key
   WORKOS_CLIENT_ID=your-workos-client-id
   ```

5. **Run the application**

   ```bash
   ./run.sh
   ```

   Or manually:

   ```bash
   uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

6. **Open in browser**

   Navigate to [http://localhost:8000](http://localhost:8000)

## Docker

### Using Docker Compose (recommended)

```bash
# Build and run
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

### Using Docker directly

```bash
# Build
docker build -t ai-rabbi .

# Run
docker run -p 8000:8000 --env-file .env ai-rabbi
```

## Development

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=backend/app --cov-report=term-missing

# Run specific test file
uv run pytest backend/tests/test_agents.py -v
```

### Code Structure

```
rabbi/
├── backend/
│   ├── app/
│   │   ├── agents/          # Multi-agent system
│   │   │   ├── base.py      # Base agent class and data models
│   │   │   ├── pastoral.py  # Pastoral context analysis
│   │   │   ├── halachic.py  # Halachic reasoning
│   │   │   ├── moral.py     # Ethical assessment
│   │   │   ├── voice.py     # Response generation
│   │   │   └── orchestrator.py
│   │   ├── auth.py          # WorkOS SSO authentication
│   │   ├── config.py        # Settings and configuration
│   │   ├── main.py          # FastAPI application
│   │   └── models.py        # Pydantic models
│   └── tests/               # Test suite
├── frontend/
│   ├── index.html           # Main HTML
│   ├── app.js               # Frontend JavaScript
│   └── styles.css           # Styles
├── pyproject.toml           # Project dependencies
├── uv.lock                  # Locked dependencies
└── Dockerfile
```

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/greeting` | Get welcome message |
| POST | `/api/chat` | Send message (non-streaming) |
| POST | `/api/chat/stream` | Send message (streaming SSE) |
| GET | `/auth/login` | Initiate SSO login |
| GET | `/auth/logout` | Log out |
| GET | `/auth/check` | Check authentication status |

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key for LLM access |
| `OPENROUTER_BASE_URL` | No | OpenRouter API base URL (default: `https://openrouter.ai/api/v1`) |
| `LLM_MODEL` | No | Model to use (default: `anthropic/claude-sonnet-4-20250514`) |
| `WORKOS_API_KEY` | No | WorkOS API key for SSO |
| `WORKOS_CLIENT_ID` | No | WorkOS client ID |
| `WORKOS_REDIRECT_URI` | No | OAuth callback URL |
| `SESSION_SECRET_KEY` | No | Secret for session tokens |

## Architecture

The system uses a pipeline architecture where each agent processes the user's message in sequence:

```
User Message
     │
     ▼
┌─────────────────────┐
│ Pastoral Context    │  Determines HOW to respond
│ Agent               │  (tone, authority level)
└─────────────────────┘
     │
     ▼
┌─────────────────────┐
│ Halachic Reasoning  │  Provides legal landscape
│ Agent               │  (majority/minority views)
└─────────────────────┘
     │
     ▼
┌─────────────────────┐
│ Moral-Ethical       │  Ensures dignity preserved
│ Agent               │  (may trigger reconsideration)
└─────────────────────┘
     │
     ▼
┌─────────────────────┐
│ Meta-Rabbinic       │  Crafts final response
│ Voice Agent         │  (warm, humble tone)
└─────────────────────┘
     │
     ▼
Final Response
```

## Design Philosophy

This project operates on several key principles:

1. **Guidance, not psak** - The AI provides information and perspective, not binding rulings
2. **Pastoral sensitivity** - Emotional context shapes how information is delivered
3. **Halachic pluralism** - Multiple valid opinions are presented, not collapsed into one
4. **Human dignity first** - A technically correct answer that causes harm is a failure
5. **Encourage human connection** - Users are directed to human rabbis for personal guidance

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- LLM access via [OpenRouter](https://openrouter.ai/)
- Authentication via [WorkOS](https://workos.com/)
- Package management with [uv](https://docs.astral.sh/uv/)
