# Dependency Audit Report

**Date:** 2026-01-26
**Project:** rebbe.dev
**Total Direct Dependencies:** 13
**Total Transitive Dependencies:** 55

## Executive Summary

After analyzing the codebase, **most dependencies are well-justified**. However, I identified **3 potential areas of bloat** where simpler alternatives could reduce bundle size and complexity:

| Dependency | Status | Potential Savings | Recommendation |
|------------|--------|-------------------|----------------|
| `openai` SDK | **Candidate for replacement** | ~5 transitive deps | Replace with raw `httpx` calls |
| `slowapi` | **Candidate for replacement** | ~3 transitive deps | Build simple rate limiter |
| `workos` | **Heavy but justified** | N/A if SSO needed | Keep if SSO required |
| All others | **Essential** | N/A | Keep |

---

## Detailed Analysis

### 1. `openai` SDK - **POTENTIAL BLOAT**

**Usage in codebase:**
- `backend/app/agents/base.py:8` - `from openai import OpenAI`
- `backend/app/agents/orchestrator.py:3` - `from openai import OpenAI`

**What we actually use:**
```python
# Client initialization
client = OpenAI(api_key=api_key, base_url=base_url)

# Regular calls
response = client.chat.completions.create(
    model=self.model,
    max_tokens=2048,
    messages=full_messages,
)

# Streaming calls
stream = client.chat.completions.create(
    model=self.model,
    max_tokens=2048,
    messages=full_messages,
    stream=True,
    stream_options={"include_usage": True},
)
```

**Transitive dependencies brought in:**
- `tqdm` (progress bars) - **NEVER USED**
- `jiter` (JSON parsing) - internal only
- `distro` (platform detection) - minimal telemetry
- `sniffio` (async detection) - minimal
- `anyio` - shared with other deps

**Why this is bloat:**
The project uses OpenRouter's OpenAI-compatible API. The OpenAI SDK is designed for the full OpenAI ecosystem (assistants, files, fine-tuning, etc.) but we only use `chat.completions.create()`.

**Replacement cost:** ~50 lines of code using `httpx` (which we already have as a dependency).

**Replacement code example:**
```python
# Instead of openai SDK
async def call_llm(messages: list, model: str, stream: bool = False):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": messages, "max_tokens": 2048, "stream": stream},
        )
        return response.json()
```

**Verdict:** **RECOMMEND REPLACING** - Reduces 5 transitive dependencies and simplifies the stack since we already use `httpx`.

---

### 2. `slowapi` - **POTENTIAL BLOAT**

**Usage in codebase:**
- `backend/app/main.py:13-15` - Import and initialization
- `backend/app/auth.py:8-9` - Import and initialization
- Decorators: `@limiter.limit("X/minute")` on ~10 endpoints

**What we actually use:**
```python
limiter = Limiter(key_func=get_rate_limit_key)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

@limiter.limit("30/minute")
async def endpoint(request: Request):
    ...
```

**Transitive dependencies brought in:**
- `limits` - core rate limiting logic
- `packaging` - version parsing (minimal)
- `deprecated` + `wrapt` - deprecation decorators

**Why this could be bloat:**
We only use basic in-memory rate limiting by IP/user ID. The `slowapi` library supports Redis, Memcached, MongoDB backends, and complex rate limiting strategies we don't use.

**Replacement cost:** ~80 lines of code for a simple in-memory rate limiter.

**Replacement sketch:**
```python
from collections import defaultdict
import time

class SimpleRateLimiter:
    def __init__(self):
        self.requests = defaultdict(list)

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        self.requests[key] = [t for t in self.requests[key] if now - t < window_seconds]
        if len(self.requests[key]) >= limit:
            return False
        self.requests[key].append(now)
        return True
```

**Verdict:** **CONSIDER REPLACING** - Only if you want to reduce dependencies. The existing usage is lightweight and `slowapi` is battle-tested.

---

### 3. `workos` - **HEAVY BUT JUSTIFIED**

**Usage in codebase:**
- `backend/app/auth.py:7` - `from workos import WorkOSClient`

**What we actually use:**
```python
client = WorkOSClient(api_key=..., client_id=...)
client.user_management.get_authorization_url(redirect_uri=..., state=..., provider="authkit")
client.user_management.authenticate_with_code(code=code)
```

**Transitive dependencies brought in:**
- `cryptography` (heavy C extension) - for JWT/crypto operations
- `cffi` + `pycparser` - C bindings for cryptography
- `pyjwt` - JWT handling

**Why it's heavy:**
The `cryptography` library is a substantial binary dependency (~15MB compiled). WorkOS SDK requires it for secure token handling.

**Why it's justified:**
WorkOS provides enterprise SSO, user management, and authentication. If these features are required, there's no simple replacement. Building OAuth2/OIDC flows manually is error-prone.

**Verdict:** **KEEP** if SSO is a product requirement. If you only need simple email/password auth, consider alternatives like:
- `authlib` (lighter)
- Direct OAuth2 with Google/GitHub (using just `httpx` + `pyjwt`)
- Session-based auth without SSO

---

### 4. `itsdangerous` - **LIGHT, KEEP**

**Usage:**
```python
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
serializer = URLSafeTimedSerializer(settings.session_secret_key)
token = serializer.dumps(user_data)
data = serializer.loads(token, max_age=86400)
```

**Why it's fine:**
- Zero transitive dependencies
- Single purpose: signed serialization
- Used exactly as intended
- Replacing it means reimplementing HMAC-based signing (security-sensitive)

**Verdict:** **KEEP** - Minimal footprint, does one thing well.

---

### 5. `pydantic-settings` - **LIGHT, KEEP**

**Usage:**
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "rebbe.dev"
    db_url: Optional[str] = None
    # ... etc
```

**Why it's fine:**
- Tightly integrated with `pydantic` (which FastAPI requires anyway)
- Only adds `typing-inspection` as a transitive dep
- Provides validated config with type coercion

**Verdict:** **KEEP** - Minimal added weight, good DX.

---

### 6. `stripe` - **ESSENTIAL FOR FEATURE**

**Usage:**
- Creating PaymentIntents
- Handling webhooks
- Customer management

**Verdict:** **KEEP** - If you need payments, Stripe SDK is the right choice. No bloat here.

---

### 7. `asyncpg` - **ESSENTIAL**

**Usage:** Direct PostgreSQL driver for async database operations.

**Verdict:** **KEEP** - It's the fastest async PostgreSQL driver for Python. No alternative is better.

---

### 8. `mangum` - **ESSENTIAL FOR DEPLOYMENT**

**Usage:** AWS Lambda adapter in `api/index.py`.

**Verdict:** **KEEP** - Required for serverless deployment. Zero-overhead when not running on Lambda.

---

### 9. `httpx` - **ESSENTIAL**

**Usage:**
- ElevenLabs TTS streaming in `main.py:452`
- Would be used more if we replace `openai` SDK

**Verdict:** **KEEP** - Already a dependency, modern async HTTP client.

---

### 10. `fastapi` + `uvicorn` + `pydantic` - **ESSENTIAL**

**Verdict:** **KEEP** - Core framework. No bloat here.

---

## Frontend Analysis

**JavaScript dependencies: ZERO**

The frontend (`frontend/app.js`) is ~1,600 lines of vanilla JavaScript with no NPM dependencies. This is excellent for performance:
- No bundler needed
- No node_modules bloat
- Stripe.js loaded dynamically only when payment modal opens

**Verdict:** **EXEMPLARY** - The frontend is already optimized.

---

## Recommendations Summary

### High Impact (Recommend)

1. **Replace `openai` SDK with raw `httpx` calls**
   - Removes: `openai`, `tqdm`, `jiter`, `distro`, `sniffio`
   - Effort: ~50 lines of code
   - Risk: Low (OpenRouter API is stable)

### Medium Impact (Consider)

2. **Replace `slowapi` with simple in-memory rate limiter**
   - Removes: `slowapi`, `limits`, `deprecated`, `wrapt`, `packaging`
   - Effort: ~80 lines of code
   - Risk: Medium (need to handle edge cases)

### No Action Needed

- `workos` - Heavy but required for SSO feature
- `stripe` - Required for payments feature
- `itsdangerous` - Minimal, single-purpose
- `pydantic-settings` - Minimal, good integration
- `asyncpg` - Best-in-class for the use case
- `mangum` - Required for Lambda deployment
- `httpx` - Already needed, modern choice
- `fastapi`/`uvicorn`/`pydantic` - Core framework

---

## Potential Savings

If both recommendations are implemented:

| Metric | Before | After | Savings |
|--------|--------|-------|---------|
| Direct deps | 13 | 11 | 2 deps |
| Transitive deps | ~55 | ~45 | ~10 deps |
| Install size | ~50MB | ~40MB | ~10MB |

---

## Conclusion

This codebase demonstrates **responsible dependency management**. Most libraries serve clear purposes with minimal overlap. The two main optimization opportunities (`openai` and `slowapi`) are worth considering if you want to minimize the dependency footprint, but they're not egregious bloat.

The frontend deserves special praise for using zero JavaScript dependencies while still delivering a full-featured chat interface with payments.
