# rebbe.dev

A source-aware Jewish guidance companion for exploring thought, practice, law, ethics, and spirituality across levels of knowledge and observance.

[![Tests](https://github.com/cheesejaguar/rabbi/actions/workflows/tests.yml/badge.svg)](https://github.com/cheesejaguar/rabbi/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

## Overview

rebbe.dev is a conversational companion for questions of Jewish thought, practice, law, ethics, and spirituality. Each answer holds four commitments: pastoral context (*how* to respond), the halachic landscape (the range of views), moral seriousness (dignity, no harm), and an honest rabbinic voice. Since pipeline v2, these live in one carefully written constitution answered by a single cached, streamed Claude Sonnet 5.5 call (served through Vercel AI Gateway), wrapped in layered guardrails:

- **Deterministic crisis floor**: crisis and abuse disclosures always get human resources first, before any model runs
- **Safety classifier** (Claude Haiku 5.5): routing and graded risk, run in parallel with source retrieval
- **Library citations**: retrieved passages are cited with the Citations API and kept separate from general-knowledge references
- **Post-answer audit**: every answer is checked, and an unsafe one is withdrawn

See [`docs/REWRITE_PLAN.md`](docs/REWRITE_PLAN.md), [`docs/SAFETY.md`](docs/SAFETY.md), and [`docs/BUSINESS_PLAN.md`](docs/BUSINESS_PLAN.md). The original four-agent pipeline is kept as a fallback (`PIPELINE_VERSION=v1`, or `GATEWAY=openrouter`).

**Important:** This is guidance, not binding psak (legal ruling). A rabbi who knows you personally may counsel differently.

## Features

- Real-time streaming responses
- WorkOS SSO authentication
- Responsive light and dark themes with a persisted system preference
- Guardrailed single-call pipeline with prompt caching (first words in about a second)
- Stop, regenerate, and edit-and-resend; conversation search and deep links
- Credit-based usage with Stripe payments, priced near cost (55 for $2, 160 for $5, 400 for $12)
- Crisis turns are always free; failed answers are refunded automatically
- Self-service data export and account deletion; 18-month retention schedule
- Public privacy policy at `/privacy` and Terms of Service at `/terms` (ages 13+)

## Quick Start

### Prerequisites

- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) package manager
- A [Vercel AI Gateway](https://vercel.com/ai-gateway) API key (Claude models are served through the gateway). OpenRouter also works, with the v1 pipeline

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
   GATEWAY=vercel
   AI_GATEWAY_API_KEY=your-ai-gateway-key

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
docker build -t rebbe .

# Run
docker run -p 8000:8000 --env-file .env rebbe
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
│   │   ├── database.py      # PostgreSQL database operations
│   │   ├── payments.py      # Stripe payment processing
│   │   ├── main.py          # FastAPI application
│   │   └── models.py        # Pydantic models
│   └── tests/               # Test suite
├── frontend/
│   ├── landing.html         # Public Source Loom landing page
│   ├── index.html           # Signed-in conversation workspace
│   ├── admin.html           # Role-protected operations workspace
│   ├── brand.css            # Shared Braided Light design tokens
│   ├── theme.js             # System/light/dark preference behavior
│   ├── app.js               # Conversation application behavior
│   └── assets/              # Local fonts, icons, identity, and imagery
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
| GET | `/api/payments/packages` | Get available credit packages |
| POST | `/api/payments/create-intent` | Create Stripe PaymentIntent |
| POST | `/api/payments/webhook` | Stripe webhook handler |

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key for LLM access |
| `OPENROUTER_BASE_URL` | No | OpenRouter API base URL (default: `https://openrouter.ai/api/v1`) |
| `LLM_MODEL` | No | Model to use (default: `anthropic/claude-sonnet-5`) |
| `WORKOS_API_KEY` | No | WorkOS API key for SSO |
| `WORKOS_CLIENT_ID` | No | WorkOS client ID |
| `WORKOS_REDIRECT_URI` | No | OAuth callback URL |
| `SESSION_SECRET_KEY` | No | Secret for session tokens |
| `STRIPE_SECRET_KEY` | No | Stripe secret key for payments |
| `STRIPE_PUBLISHABLE_KEY` | No | Stripe publishable key for frontend |
| `STRIPE_WEBHOOK_SECRET` | No | Stripe webhook signing secret |
| `DATABASE_URL` | No | PostgreSQL connection URL |

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
- Payments via [Stripe](https://stripe.com/)
- Package management with [uv](https://docs.astral.sh/uv/)
