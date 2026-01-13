# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

rebbe.dev is a multi-agent chatbot providing Torah wisdom and guidance from a progressive Modern Orthodox perspective. It uses Claude as the underlying LLM and implements a four-stage agent pipeline to process user messages.

## Development Commands

```bash
# Run locally (creates venv, installs deps, starts server)
./run.sh

# Run with Docker
docker compose up --build

# Run manually (after activating venv)
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The app runs at http://localhost:8000

## Configuration

Copy `.env.example` to `.env` and set:
- `OPENROUTER_API_KEY` or `AI_GATEWAY_API_KEY` (required for LLM)
- `LLM_MODEL` (optional, defaults to anthropic/claude-sonnet-4-20250514)
- `WORKOS_API_KEY` and `WORKOS_CLIENT_ID` (for authentication)
- `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` (for payments)
- `DATABASE_URL` (PostgreSQL connection string)

## Architecture

### Multi-Agent Pipeline

User messages flow through four sequential agents in `backend/app/agents/`:

1. **PastoralContextAgent** (`pastoral.py`) - Determines *how* to respond: emotional state detection, pastoral mode (teaching/counseling/crisis/curiosity), tone constraints, vulnerability detection
2. **HalachicReasoningAgent** (`halachic.py`) - Provides halachic landscape: majority/minority views, underlying principles, precedents for leniency
3. **MoralEthicalAgent** (`moral.py`) - Ensures dignity preservation and harm prevention; can trigger reconsideration loop
4. **MetaRabbinicVoiceAgent** (`voice.py`) - Crafts final response with appropriate rabbinic tone and humility

The `RabbiOrchestrator` (`orchestrator.py`) coordinates this pipeline. If the moral agent flags concerns, it triggers a reconsideration loop back through halachic reasoning.

### Key Data Structures (`base.py`)

- `AgentContext` - Shared context passed through pipeline
- `PastoralContext` - Mode, tone, authority level, crisis indicators
- `HalachicLandscape` - Structured halachic analysis
- `MoralAssessment` - Harm assessment with reconsideration flag

### API Endpoints (`main.py`)

- `GET /api/health` - Health check
- `GET /api/greeting` - Initial greeting message
- `POST /api/chat` - Main chat endpoint (processes through full pipeline)

### Payment Endpoints (`payments.py`)

- `GET /api/payments/packages` - Available credit packages (10 for $1, 25 for $2)
- `POST /api/payments/create-intent` - Create Stripe PaymentIntent and CustomerSession
- `POST /api/payments/webhook` - Handle Stripe webhook events (payment success/failure)
- `POST /api/payments/verify-and-fulfill` - Client-side verification (non-production only)

### Database (`database.py`)

PostgreSQL with asyncpg. Key tables:
- `users` - User accounts with credits balance and stripe_customer_id
- `conversations` - Chat conversation metadata
- `messages` - Individual messages in conversations
- `purchases` - Credit purchase history with Stripe payment intent IDs

Schema auto-initializes on startup with advisory locks for concurrent safety.

### Frontend

Static files in `frontend/` served at root. Vanilla HTML/JS/CSS chat interface with Stripe Elements for payments.

## Design Principles

This system prioritizes pastoral responsibility over halachic maximalism. Key constraints:
- If vulnerability detected, halachic maximalism is prohibited
- A technically correct answer that causes harm is a system failure
- Always recommend consultation with human rabbis
- Present ranges of opinion, not single conclusions
