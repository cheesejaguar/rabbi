# rebbe.dev — Missing Features & Improvements Audit

An exhaustive audit of what stands between the current codebase and a service
people would pay for and trust — plus everything an administrator needs to
monitor and moderate the platform. Every finding is grounded in the code as of
this audit; file references point at the evidence.

Severity: **critical** = blocks being a trustworthy paid service ·
**high** = major value/retention/ops gap · **medium** = meaningful improvement ·
**low** = polish. Effort: S / M / L.

> **Addressed on this branch (`claude/missing-features-admin-tools`):** admin
> role with `ADMIN_EMAILS` bootstrap (cheesejaguar@gmail.com is the default
> administrator), `/api/admin/*` endpoints (overview, users, credit grants,
> role management, crisis queue, feedback queue, error browser, purchases,
> analytics, LLM cost stats, audit log), the `/admin` dashboard UI, an
> `admin_audit_log` table, user sync + admin promotion at login, and
> persistence of pipeline metadata (crisis flags, sources) with each saved
> message. Everything else below remains open.

---

## Top 10 priorities

1. **Out-of-credits dead-ends at "contact support"** instead of opening the
   purchase modal — the single highest-intent monetization moment is lost
   (critical, S).
2. **Crisis handling has no deterministic floor**: no hotline numbers ever
   guaranteed, no human alerting, guest crisis signals discarded, and the
   pastoral agent's parse-failure fallback fails *open* (critical, M).
   The new admin crisis queue surfaces flagged messages, but real-time
   notification and a hard-coded crisis-resources response are still missing.
3. **No Terms of Service or Privacy Policy** while charging money and storing
   religious/emotional conversations — a legal non-starter (critical, M).
4. **RAG citations are never shown to users** (and are unverified LLM output)
   — verifiable sources are the core trust feature of a paid Torah product
   (critical, M).
5. **In-memory rate limiting / abuse state is broken on serverless** — guest
   limits, IP blocks, and login rate limits reset per instance and are
   spoofable via X-Forwarded-For (high, M).
6. **Multi-turn context is broken**: 3 of 4 agents never see conversation
   history, so follow-up questions silently lose context (high, M).
7. **No error tracking or alerting**: errors are written to a table nobody is
   notified about; the health check is a static 200 (high, S–M).
8. **Pricing model can't sustain the product**: $1–$2 max purchase, no
   subscription, no receipts, no refunds handling (high, M–L).
9. **No account deletion / data export** — GDPR/CCPA obligations unmet for
   special-category (religious) data collected without consent (high, M).
10. **No retention loop**: no email digest, no push, no Shabbat/holiday-aware
    experience, no reason to come back (high, M–L).

---

## 1. Product & monetization

- **[critical/S] Out-of-credits dead-end.** Backend streams "No credits
  remaining. Please contact support." (`main.py`); the frontend only
  special-cases `guest_limit_reached`, so paying-ready users see a generic
  error bubble instead of `openPurchaseModal()` (`app.js`).
- **[high/L] No subscriptions or recurring revenue.** Only one-shot
  PaymentIntents (`payments.py`); no Stripe Prices/Subscriptions, no MRR, no
  card-on-file loop.
- **[high/S] Pricing ceiling is $2.** Two packages (10/$1, 25/$2). No larger
  bundles, premium tier, or annual plan; unit economics leave no headroom over
  LLM/TTS costs.
- **[high/M] Purchase entry buried in Settings.** Buy Credits and the balance
  only exist in the Settings screen; no header balance, low-credit warning, or
  in-chat paywall.
- **[high/M] No receipts, invoices, or purchase history UI.**
  `db.get_user_purchases()` exists but has no route; PaymentIntents are created
  without `receipt_email`.
- **[high/M] No refund/dispute handling.** The `refunded` status is dead code;
  webhook ignores `charge.refunded` / disputes, so charged-back users keep
  credits.
- **[high/L] No retention mechanics.** No email digests, holiday/yahrzeit
  reminders, study plans, bookmarks, or push. WorkOS captures an email that is
  never used.
- **[high/M] Free-trial funnel broken.** Backend allows 1 guest chat, but the
  frontend forces sign-in before any message (`sendFromWelcome`), so the
  no-login trial is unreachable; then only 3 credits before the wall.
- **[medium/L] No B2B/community plans.** No organizations, seats, or site
  licenses for synagogues, schools, Hillels — the highest-value buyers.
- **[medium/M] No referrals, gifting, or promo codes.** Stripe
  Coupons/PromotionCodes unused; no "give credits to a friend."
- **[medium/L] No Hebrew localization or RTL.** `lang="en"` hardcoded; no
  i18n, no RTL handling — the Israeli market is unreachable.
- **[medium/M] Not installable.** No manifest.json or service worker; no
  offline shell; no web push channel.
- **[medium/S] No credit lifecycle UX.** No expiry policy, no "1 credit left"
  warning, no auto-reload; credits framed as "help us manage API costs" rather
  than value.

## 2. Trust, safety & compliance

- **[critical/M] No deterministic crisis resources.** Crisis detection exists
  (`pastoral.py`) but whether a suicidal user gets a hotline (988 etc.) is left
  to model discretion ("Provides crisis resources if appropriate",
  `voice.py`). Nothing in the codebase contains a hotline number.
- **[critical/M] No human escalation on crisis.** No notification (email/
  Slack/on-call) fires when `requires_human_referral` or crisis indicators are
  set. *(The admin crisis queue added on this branch gives after-the-fact
  review; real-time alerting is still missing.)*
- **[critical/M] Guest crisis signals discarded.** Metadata is persisted only
  for logged-in users with a conversation; a guest disclosing suicidal
  ideation leaves no reviewable trace.
- **[critical/M] No Terms of Service.** No page, route, or link — while taking
  payments for counseling-adjacent output.
- **[critical/M] No Privacy Policy.** Stores religious affiliation (GDPR
  Art. 9 special-category), emotional conversations, IPs, fingerprints, and
  anonymous analytics with no privacy notice.
- **[high/M] No account deletion (right to erasure).** Schema supports cascade
  deletion but no endpoint or UI exists.
- **[high/S] No "not therapy" disclaimer.** Only the halachic "not psak"
  disclaimer exists; nothing says it is not therapy or professional care.
- **[high/M] No consent for special-category data.** Denomination and
  emotional content stored with no opt-in.
- **[high/M] No age gating.** Any age can sign in, disclose mental-health
  content, and pay (COPPA/GDPR-minor exposure).
- **[medium/L] No LLM output moderation.** Voice-agent tokens stream verbatim
  to the client; the moral agent runs *before* final generation and checks
  dignity only.
- **[medium/M] No data-retention policy.** Nothing expires; LLM failures copy
  up to 500 chars of the user's (possibly crisis) message into the errors
  table forever.
- **[medium/M] No cookie consent** despite anonymous analytics tracking and
  fingerprinting.
- **[medium/M] No data export (portability).**
- **[medium/S] Crisis parse-failure fails open.** If pastoral JSON parsing
  fails, the fallback sets mode=CURIOSITY and leaves
  `requires_human_referral=False` — the opposite of fail-safe
  (`pastoral.py:197-205`).
- **[low/S] Moral framing discarded.** `moral_framing` is parsed into a local
  variable and never attached to `MoralAssessment` (`moral.py:222`), so the
  dignity-framing guardrail never reaches the voice agent.
- **[low/S] Email verification not checked** at the app layer
  (`auth.py` callback trusts WorkOS config entirely).
- **[low/S] Streamed responses invisible to screen readers** (no `aria-live`
  on the chat container or referral banner).

## 3. Admin & moderation

*(Foundation shipped on this branch: admin role, `/api/admin/*`, `/admin`
dashboard, audit log. The items below are what remains.)*

- **[high/M] Real-time crisis alerting.** The queue exists; nobody is paged.
  Add email/webhook notification when a crisis flag is persisted.
- **[high/M] Ban/suspend users.** No `status`/`banned` column; no way to shut
  off an abusive paying account — and sessions can't be revoked (see
  Security), so even a flag wouldn't cut off an active session.
- **[high/M] Refund tooling.** No Stripe refund flow, no credit clawback, no
  handling of `charge.refunded`/dispute webhooks.
- **[high/M] Abuse/IP-block visibility & control.** The blocklist is an
  in-process dict (`security.py`); admins cannot list, add, or lift blocks
  (false positives are permanent until restart).
- **[medium/M] Full-text message/conversation search** for investigating
  abuse reports (current admin review is per-user browse only).
- **[medium/M] Announcement/banner system** (site-wide notices without a
  deploy).
- **[medium/M] Feature flags** (e.g., disable TTS or guest access at runtime).
- **[medium/L] Prompt/config management without redeploys.** All four agent
  prompts, the model id, and every limit are hardcoded/env-static.
- **[medium/M] Runtime rate-limit tuning** (limits are baked into decorators
  and captured at import).
- **[medium/M] GDPR tooling for admins** (export/erase a user across all
  tables on request).
- **[medium/S] Wire `log_error` into all failure paths.** Only the streaming
  chat path persists errors; `/api/chat`, `/api/speak`, d'var Torah, and
  profile/feedback failures only hit `logger.error`.
- **[low/M] Support inbox/contact channel.** "Contact support" is mentioned to
  users but no contact mechanism exists anywhere.

## 4. Security

- **[high/L] No session revocation or refresh.** Stateless 24h cookies;
  logout is client-side only; stolen cookies stay valid; deprovisioned users
  keep access up to 24h.
- **[high/M] In-memory abuse state broken on serverless.** Guest quotas,
  fingerprints, and blocklists are per-process and wiped on cold start
  (`security.py` docstring admits Redis is needed).
- **[high/M] Rate limiting is per-instance.** Both slowapi `Limiter`s have no
  shared storage backend.
- **[high/M] X-Forwarded-For is trusted blindly.** `_get_client_ip` takes the
  leftmost client-controlled value — all IP-based defenses are spoofable, and
  victims can be framed into the blocklist.
- **[high/S] Single point of failure: `ENVIRONMENT=production`.** If unset,
  cookies are non-Secure, HSTS off, secret-key validation skipped, CORS check
  skipped, and the dev-only `verify-and-fulfill` payment path stays enabled.
  Consider failing closed instead.
- **[medium/S] No Content-Security-Policy** (or COOP/CORP) despite rendering
  LLM output and embedding Stripe.js/Google Fonts.
- **[medium/M] No CSRF tokens**; relies solely on SameSite=Lax, with a
  GET-based logout.
- **[medium/M] Prompt-injection "detection" is log-only** and pattern-based;
  nothing blocks or structurally mitigates.
- **[medium/M] No account lockout / authenticated-abuse controls.**
- **[medium/M] PII in logs.** Message excerpts in the errors table, raw IPs
  and user agents at WARNING level to stdout.
- **[medium/M] Session secret has a weak default and no rotation strategy.**
- **[low/S] Public analytics endpoint accepts arbitrary JSONB writes**
  (storage exhaustion / data pollution).
- **[low/S] pip-audit and ruff are `continue-on-error` in CI; no
  Dependabot/Renovate.**

## 5. Reliability, observability & operations

- **[high/S] No error-tracking service** (Sentry/Datadog/OTel absent).
- **[high/M] Errors table write-only; no alerting.** *(Now browsable via the
  admin dashboard; alerting still missing.)*
- **[high/S] Shallow health check.** `/api/health` never touches the DB or
  LLM gateway; monitors will report healthy during a full outage.
- **[high/M] Sync LLM client blocks the event loop.** All agents call the
  synchronous OpenAI client inside `async def`, serializing all concurrent
  traffic for the multi-second pipeline (`base.py`, `orchestrator.py`).
- **[high/M] No LLM timeout/retries/failover.** SDK default ~600s timeout; the
  Vercel-vs-OpenRouter gateway choice is static with no runtime fallback.
- **[high/S] No Vercel `maxDuration`.** The 4+ sequential LLM call pipeline
  can be killed mid-stream at the default function limit (frontend has a 90s
  watchdog expecting slowness).
- **[medium/M] D'var Torah stale-lock.** A crash between claim and completion
  leaves `generating=TRUE` forever; the weekly feature stays broken until
  manual DB surgery.
- **[medium/M] No structured logging or correlation IDs.** Impossible to trace
  one request across the four agents.
- **[medium/L] No migration tooling.** One raw `SCHEMA_SQL` string with
  hand-written DO-blocks; no Alembic, no rollback path.
- **[medium/S] Pool sizing vs serverless.** Up to 10 connections per instance
  can exhaust Neon's ceiling under fan-out.
- **[medium/M] No staging environment or deploy gate;** effectively
  push-to-main.
- **[medium/M] No backup/DR runbook or uptime monitoring/status page.**
- **[medium/M] LLM cost aggregation.** *(Basic per-day cost rollup now exists
  at `/api/admin/costs`; per-user caps and runaway-spend alerts still
  missing; the price table in `base.py` is hardcoded and will drift.)*
- **[low/S] Non-streaming `/api/chat` bypasses credits and error logging**
  entirely — a billing-consistency hole relative to the streaming path.

## 6. Answer quality & AI architecture

- **[critical/M] Citations never reach the user.** The orchestrator sends
  `sources_cited` to the browser and the frontend discards it; `voice.py`
  even instructs the model to avoid footnotes. No links to Sefaria or
  primary texts anywhere.
- **[high/M] Citation fidelity unenforced.** `sources_cited` is free-form LLM
  output never validated against retrieved chunks — hallucinated citations
  are possible in a halachic product.
- **[high/L] RAG is hand-rolled TF-IDF.** No embeddings; the benchmark itself
  documents that common biblical words swamp results and Hebrew-with-nikud
  fails to match; acceptance thresholds are set low (recall ≥ 0.4).
- **[high/L] No answer-quality eval harness.** Only chunk retrieval is
  benchmarked; every agent test mocks the LLM. No golden answers, no
  LLM-as-judge, no safety-behavior regression tests.
- **[high/M] Multi-turn context broken.** Only the pastoral agent sees history
  (last 3 messages, 200 chars each); halachic, moral, and voice agents get a
  single message — follow-ups lose all context.
- **[medium/M] No token-window management or summarization** for long
  conversations (unbounded client-supplied history up to 100 messages).
- **[medium/S] One model, no temperature or JSON mode.** Three agents must
  emit strict JSON at default temperature with no `response_format`; parse
  failures silently fall back to canned defaults.
- **[medium/M] No prompt versioning or A/B experimentation;** answers can't be
  attributed to a prompt version.
- **[medium/M] Feedback unused downstream.** *(Now reviewable in the admin
  dashboard; still not fed into evals or prompt iteration.)*
- **[medium/S] RAG index drift.** The committed 41MB index is never rebuilt or
  verified in CI against `library/`.
- **[medium/S] No type checking; lint non-blocking.** No mypy/pyright; ruff is
  `continue-on-error`.
- **[medium/S] Webhook tests bypass signature verification** and idempotent
  double-delivery; coverage config omits `auth.py` entirely.
- **[low/M] Schema scale concerns.** TEXT PKs everywhere; `messages.metadata`
  JSONB has no GIN index for analytical queries; feedback lacks a
  `created_at` index.
- **[low/M] No warehouse/ETL path** — analytics queries hit the OLTP database.

## 7. User experience & frontend

- **[high/M] Markdown rendering is bold/italic only.** No lists, headings,
  links, blockquotes, code, or even paragraph breaks — long answers render as
  a wall of text.
- **[high/S] No stop-generation button.** Once streaming starts it cannot be
  cancelled.
- **[high/M] No regenerate / edit-and-resend / retry.** Failures produce a
  static error bubble; users must retype.
- **[high/L] No Hebrew/RTL rendering.** No `dir` handling, no Hebrew webfont,
  no bidi isolation, no transliteration/nikud options.
- **[high/M] Accessibility gaps.** JS-built action buttons lack aria-labels,
  no `:focus-visible` styles, no live regions, no modal focus trap, blocking
  `window.alert()` for errors.
- **[medium/M] No conversation search** or pinning/grouping in the sidebar.
- **[medium/M] No sharing/export.** Copy pastes raw markdown; no share links,
  PDF/markdown export, or email — forfeits organic growth for highly
  shareable content.
- **[medium/M] Dark theme only;** no light theme or `prefers-color-scheme`.
- **[medium/S] Weak error recovery.** No retry affordance, no transient-vs-
  terminal distinction.
- **[medium/M] Thin onboarding.** Four hardcoded suggestion chips; nothing
  explains credits or capabilities; no parsha- or denomination-aware
  suggestions despite having the data.
- **[medium/L] No d'var Torah email digest or notification preferences.**
- **[medium/M] Settings incomplete.** No editable name, notifications, theme,
  language, TTS voice/speed, purchase history, export, or deletion.
- **[low/M] TTS is play/stop only** — no pause, seek, speed, voice choice, or
  progress.
- **[low/L] No i18n scaffolding** (hardcoded English strings throughout).
- **[low/M] Streaming re-render is O(n²)** (`formatMarkdown` re-runs over the
  full accumulated text per token) and the d'var Torah view injects unescaped
  `innerHTML`.

## 8. Market & domain gaps (the ones only this product has)

- **[high/M] No public landing page or SEO surface.** Unauthenticated visitors
  and crawlers are 302'd to a bare "Sign in to continue" page; no /about,
  /pricing, /faq, robots.txt, or sitemap — no organic acquisition funnel at
  all.
- **[high/S] No Shabbat/Yom Tov awareness.** `pyluach` is already a dependency
  (used for parsha), yet the chat and purchase flows are calendar-blind. A
  Shabbat-mode notice is cheap and signals authenticity to the observant
  audience.
- **[high/M] No rabbinic endorsement/supervision trust signals.** The product
  says what it is *not* (not psak, not a rabbi) but names no rabbi,
  institution, or advisory board that stands behind it — decisive for this
  audience's willingness to pay.
- **[medium/M] No human-rabbi referral fulfillment.** The pipeline constantly
  recommends "ask your rabbi" but offers no directory, partner network, or
  escalation path.
- **[medium/M] No tzedakah/sponsorship revenue model.** Jewish learning is
  traditionally funded by sponsorship and dedications ("sponsor this week's
  d'var Torah in memory of…") — a culturally native, zero-marginal-cost
  revenue lever the credit model ignores.
- **[medium/M] No voice input** (TTS out only); the Permissions-Policy header
  currently disables the microphone.
- **[medium/L] No community features or public Q&A archive** — no anonymized
  answered-questions knowledge base (which would double as the missing SEO
  content).
- **[medium/L] No integrations/distribution.** No public API, no embeddable
  widget for synagogue sites, no Sefaria deep links from citations.
- **[medium/S] No user-facing "report this answer" button and no appeal path
  for blocked guests.**
