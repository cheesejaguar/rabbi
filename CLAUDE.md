# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

rebbe.dev is a chatbot providing Torah wisdom and guidance from a progressive Modern Orthodox perspective. It uses Claude directly (Anthropic API). The default **pipeline v2** wraps one cached, streamed Sonnet 5.5 call in layered guardrails; the legacy four-agent **v1** pipeline remains as a fallback. See `docs/REWRITE_PLAN.md`, `docs/SAFETY.md`, `docs/API_CONTRACT_V2.md`, `docs/BUSINESS_PLAN.md`.

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
- `ANTHROPIC_API_KEY` (pipeline v2; without it the app falls back to v1)
- `PIPELINE_VERSION` (`v2` default), `GENERATION_MODEL` (`claude-sonnet-5-5`), `CLASSIFIER_MODEL`/`AUDIT_MODEL` (`claude-haiku-5-5`)
- `ADMIN_ALERT_WEBHOOK_URL` (real-time crisis alerts), `FREE_TIER_DAILY_BUDGET_USD`, `TTS_CREDIT_COST`, `SIGNUP_CREDITS`, `RETENTION_DAYS`
- `OPENROUTER_API_KEY` or `AI_GATEWAY_API_KEY` (v1 fallback, d'var Torah generation)
- `LLM_MODEL` (optional, defaults to anthropic/claude-sonnet-5)
- `PASTORAL_CLASSIFIER` (optional, `jev` default or `llm`) - `jev` needs `OPENROUTER_API_KEY`
- `WORKOS_API_KEY` and `WORKOS_CLIENT_ID` (for authentication)
- `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` (for payments)
- `DATABASE_URL` (PostgreSQL connection string)

## Architecture

### Pipeline v2 (default) — `backend/app/chat/`, `backend/app/safety/`, `backend/app/prompts/`, `backend/app/llm/`

`chat/endpoint.py` (limits, credits charged once per `request_id`, history from DB, edit/regenerate, persistence) → `chat/pipeline.py`:

1. `safety/lexicon.py` — deterministic crisis/abuse floor; a match emits the `safety_resources` card before any model call
2. `safety/classifier.py` (Haiku 5.5, structured output) **in parallel with** `chat/retrieval.py` (library index, multi-query)
3. `safety/policy.py` — pure function: overlays, effort, card, charge (crisis turns free and never walled)
4. One streamed Sonnet 5.5 call: frozen `prompts/constitution.md` (1h cache) + profile block + history + library passages as citable `search_result` blocks + mid-conversation system overlay; `fallbacks: "default"`
5. `safety/audit.py` (Haiku) after `done`; `severe` → `retraction` event

Prices live only in `llm/pricing.py`. Keep the constitution free of dates/IDs (cache prefix). Evals: `backend/evals/run_evals.py` (`--offline` runs in CI via `test_v2_safety.py`).

### Legacy Multi-Agent Pipeline (v1 fallback)

User messages flow through four sequential agents in `backend/app/agents/`:

1. **PastoralContextAgent** (`pastoral.py`) - Determines *how* to respond: emotional state detection, pastoral mode (teaching/counseling/crisis/curiosity), tone constraints, vulnerability detection. Asks Jev first (`jev.py`, one request for every question, crisis-biased thresholds) and only calls the LLM when Jev fails or is unsure
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

- `GET /` - App for signed-in users; public SEO landing page (`frontend/landing.html`) for visitors
- `GET /api/health` - Health check
- `GET /api/greeting` - Initial greeting message
- `POST /api/chat` - Non-streaming chat (v1 pipeline)
- `POST /api/chat/stream` - Streaming chat (v2 when configured; SSE contract in `docs/API_CONTRACT_V2.md`)
- `GET /api/account/export`, `DELETE /api/account` - Self-service data export / account deletion (`account.py`)
- `GET /terms` - Terms of Service (ages 13+); `GET /c/{id}` - conversation deep link
- `GET /api/dvar-torah` - Weekly d'var Torah with sponsor dedications
- `GET /api/calendar-status` - Shabbat/yom tov status for the client's local time (`jewish_calendar.py`)
- `GET /robots.txt`, `GET /sitemap.xml` - Crawler surface

### Payment Endpoints (`payments.py`)

- `GET /api/payments/packages` - Credit packages (55/$2, 160/$5 recommended, 400/$12; legacy 10/25 ids retired)
- `POST /api/payments/create-intent` - Create Stripe PaymentIntent and CustomerSession
- `GET /api/payments/sponsorship-tiers` - D'var Torah sponsorship tiers (chai multiples)
- `POST /api/payments/create-sponsorship-intent` - Sponsor the week's d'var Torah with a dedication
- `POST /api/payments/webhook` - Handle Stripe webhook events; dispatches purchases vs sponsorships via `metadata.type`
- `POST /api/payments/verify-and-fulfill` - Client-side verification (non-production only)

### Admin Endpoints (`admin.py`)

Administrator-only endpoints for monitoring and moderation. Admin status comes from the `ADMIN_EMAILS` setting (comma-separated, defaults to the platform owner) or the `users.is_admin` flag granted at runtime; both are enforced by the `require_admin` dependency. Mutations and conversation views are recorded in `admin_audit_log`.

- `GET /admin` - Admin dashboard UI (`frontend/admin.html`)
- `GET /api/admin/overview` - Users, activity, revenue, error, feedback counters
- `GET /api/admin/users` - Searchable user list; `POST .../{id}/credits` and `POST .../{id}/role` adjust credits / grant-revoke admin
- `GET /api/admin/flagged` - Crisis / human-referral / audit-concern review queue (from message metadata)
- `GET /api/admin/safety-events` - v2 safety events incl. guest turns, plus today's free-tier spend
- `GET /api/admin/feedback` - Thumbs-up/down review queue with message excerpts
- `GET /api/admin/errors` - Error log browser plus daily aggregates
- `GET /api/admin/purchases` - Purchases across all users
- `GET /api/admin/analytics` - Session/referrer/device/TTS stats
- `GET /api/admin/costs` - Estimated LLM spend per day
- `GET /api/admin/audit-log` - Trail of admin actions

### Database (`database.py`)

PostgreSQL with asyncpg. Key tables:
- `users` - User accounts with credits balance, is_admin flag, and stripe_customer_id
- `conversations` - Chat conversation metadata
- `messages` - Individual messages in conversations
- `purchases` - Credit purchase history with Stripe payment intent IDs
- `sponsorships` - D'var Torah dedications (tzedakah) tied to a parsha/Hebrew year
- `admin_audit_log` - Immutable trail of privileged admin actions
- `rate_limits` - Fixed-window counters shared across instances (`ratelimit.py`)
- `credit_ledger` - Every credit change; unique `(reason, ref)` makes charges/refunds idempotent
- `safety_events` - Crisis/abuse/harm/audit events (18-month retention); `free_tier_spend` - daily guest spend

Schema auto-initializes on startup with advisory locks for concurrent safety.

### Frontend

Static files in `frontend/` served at root. No build step: native ES modules under `frontend/app/`, vendored pinned libs in `frontend/vendor/`, Stripe Elements for payments.

## Design Principles

This system prioritizes pastoral responsibility over halachic maximalism. Key constraints:
- If vulnerability detected, halachic maximalism is prohibited
- A technically correct answer that causes harm is a system failure
- Always recommend consultation with human rabbis
- Crisis resources are server-authored static content (`safety/resources.py`), never model-generated; crisis turns are free and never blocked by limits
- Users are 13+; minors get age-appropriate overlays
- Present ranges of opinion, not single conclusions
