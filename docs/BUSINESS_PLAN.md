# rebbe.dev — Business Plan (post-rewrite)

Status: **adopted**. The new packs and the free-tier budget ship with pipeline v2 · Pricing goal: **cost plus about 4%**, enough to keep the lights on, not a profit engine · Model: [`unit_economics.py`](unit_economics.py) (run it to reproduce every number below) · Architecture: [`REWRITE_PLAN.md`](REWRITE_PLAN.md)

## 1. What we sell

A private, source-aware Jewish guidance companion: questions of practice, text, ethics, and personal struggle, answered with a range of views, real citations, and an honest referral to a human rav when needed. The audience is Jewishly curious adults across observance levels (see `PRODUCT.md`). It is a consumer product: people pay small amounts occasionally, not through enterprise contracts.

Revenue lines:
1. **Message credits** (main line). 1 credit = 1 answered message. Crisis turns are always free.
2. **D'var Torah sponsorships** (chai tiers: $18 / $36 / $54 / $180). These are dedications. Treat their net proceeds as funding for the free tier and crisis turns, not as profit.
3. **Premium voice (TTS)**: optional, charged in credits (§4).

## 2. Cost structure

### 2.1 Variable cost per message (LLM)

Token assumptions: constitution about 3.5k tokens (cached), history about 1.5k, retrieved passages about 2k, output about 700 plus about 200 thinking. Prices are current Claude API list prices per 1M tokens.

| Pipeline | Calls per message | Est. cost / message |
|---|---|---|
| **Current** (Jev + Sonnet 5 × 3, +20% reconsideration, no caching) | 4–5 | **$0.0443** (+5.5% gateway fee → $0.0467) |
| **Proposed, Sonnet 5.5** (Haiku guard + 1 cached Sonnet call + Haiku audit) | 3 (1 large) | **$0.0192** |
| Proposed, Opus 5.5 instead | 3 (1 large) | $0.0374 |

Breakdown of the proposed Sonnet 5.5 pipeline: classifier $0.0001, audit $0.0002, generation $0.0159 with a warm cache or $0.0257 cold (blended at a 70% warm rate = $0.0189).

So the rewrite cuts LLM cost per message by about **57%** and time to first token by about **90%**. Both come from the same change: one cached call instead of four sequential uncached ones, sent directly to the API.

> Note: the in-app cost dashboard currently prices `claude-sonnet-5` at $3/$15 and overstates spend by about 50%. Phase 0 of the rewrite fixes this.

### 2.2 Other per-message costs

| Item | Assumption | Per message |
|---|---|---|
| Infra variable (function time, DB, bandwidth) | estimate | $0.0010 |
| Free-tier subsidy | free messages = 15% of paid volume | +15% of variable cost |
| Loss buffer (refunds, disputes, failed generations) | 3% | +3% |

### 2.3 Fixed monthly costs (estimates; replace with real invoices)

| Item | Est. / month |
|---|---|
| Vercel Pro | $20 |
| Neon Postgres (Launch) | $19 |
| Domain, email, monitoring free tiers, misc | ~$26 |
| WorkOS AuthKit | $0 (free under 1M MAU) |
| **Total** | **~$65** |

### 2.4 Payment processing: the hidden majority cost

Stripe charges **2.9% + $0.30 per payment**. On today's $1 pack the fee is **33%** of revenue, more than the LLM cost of that pack. At a 4% margin, small packs cannot be sustained, so the price ladder starts at $2 and steers people toward $5.

### 2.5 Fully loaded cost per message (proposed pipeline)

| Monthly messages | Loaded cost / message |
|---|---|
| 5,000 | $0.0373 |
| 15,000 | $0.0283 |
| **25,000 (planning volume)** | **$0.0266** |
| 100,000 | $0.0245 |

Below about 15k messages a month, the $65 fixed overhead dominates and a 4% price loses money. Sponsorship income should cover that gap at launch (about four $18 chai sponsorships a month, net of Stripe fees, cover all fixed costs).

## 3. Pricing

### 3.1 Recommended credit packs (replacing 10/$1 and 25/$2)

Priced from the loaded cost at 25k messages a month, then rounded to friendly numbers:

| Pack | Price | Per message | Margin @15k/mo | @25k/mo | @100k/mo |
|---|---|---|---|---|---|
| Starter | **$2 → 55 credits** | $0.036 | 5.4% | 12.4% | 21.6% |
| Standard *(default)* | **$5 → 160 credits** | $0.031 | 0.5% | 7.2% | 16.0% |
| Plus | **$12 → 400 credits** | $0.030 | 0.1% | 6.9% | 15.6% |

The strict 4% sizes at 25k/month are 59 / 165 / 411 credits. The rounded ladder above keeps a few points of cushion at planning volume because the 25k figure is a guess. **Re-price each quarter** from measured cost (admin `/api/admin/costs`): as volume grows, increase the credits per pack rather than raising prices.

Compared with today, users get about **3× more messages per dollar** ($0.031 vs $0.08–$0.10 per message), and the margin comes from efficiency, not from charging more.

Compatibility: keep the `credits_10` and `credits_25` IDs readable for purchase history, and add `credits_55`, `credits_160`, `credits_400`. The `PRODUCT.md` pricing contract needs updating.

### 3.2 Free usage (acquisition, budgeted rather than unlimited)

| Who | Today | Proposed |
|---|---|---|
| Guest | 3/day per IP (counter is in memory, so effectively unlimited on serverless) | **3 total per device** (signed cookie, fingerprint, and Postgres-backed IP cap), plus Turnstile |
| New account | 3 credits | **10 credits once** (about $0.27 of cost, a reasonable acquisition cost) |
| Crisis turns | charged like normal turns | **always free, never walled** |
| Global | none | **daily free-tier dollar cap**; when reached, guests are asked to sign in |

At a 4% margin, free usage cannot be paid for out of credit sales alone. It is funded by the cushion in §3.1 and by sponsorships, and the daily cap keeps it bounded.

### 3.3 Optional later: subscription

A **$4.99/month "Chaver" plan with about 175 messages** (fair-use soft cap) pays Stripe's $0.30 once a month instead of on every top-up. It suits regular learners. Add it only after pack data shows repeat buyers.

## 4. Text-to-speech

ElevenLabs costs roughly $0.11–$0.22 per 1k characters (verify against the current plan). A typical 2,500-character answer costs **$0.27–$0.55 to voice, 10–25× the text reply**. Options:
- **Default: browser `speechSynthesis`.** Free and immediate.
- **Premium voice: 8 credits per listen** (about $0.25), cached per message so repeat listens are free.

## 5. Current state, for comparison

Today's packs earn about **41–44% gross margin on LLM cost for paid messages**. Two things erase that: (a) Stripe takes 18–33% of each purchase, which is already counted in the 41–44%; (b) the free tier (3 guest chats per IP per day, which the serverless in-memory counter does not actually enforce, plus 3 signup credits) and unpriced TTS are subsidized out of the same margin, and their volume is unbounded. Users are also paying 3× more per message than they need to. The rewrite lowers the user's price and makes the remaining margin predictable.

## 6. Key metrics (admin dashboard)

- Cost per message (measured, by model and mode) and cache hit rate
- Time to first token p50/p95
- Paid conversion (guest → account → first purchase) and repeat purchase rate
- Free-tier spend per day versus the cap
- Crisis turns per week, resource-card display rate (target 100% on flagged turns), admin response time
- Audit pass rate and user thumbs-up rate (quality guardrail on any cost change)

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Volume below 15k/month → loss at 4% | Sponsorship income covers fixed costs; re-price quarterly; the cushion in the rounded packs |
| Model price changes | Single pricing module; packs re-sized, not re-priced |
| Abuse draining free-tier spend | Postgres limits, Turnstile, daily dollar cap, per-device caps |
| A safety failure (the existential risk) | Deterministic crisis floor, eval gates in CI, post-stream audit, human alerting, ToS and "not for emergencies" copy |
| Chargebacks ($15 each) | 3% loss buffer; Stripe Radar; refund unused credits on request instead of disputing |

## 8. Assumptions to verify before launch

Token counts (measure after Phase 2), cache warm rate (70%), free share (15%), fixed costs ($65), ElevenLabs rate, and Stripe's rate for your account (Link, international cards, and currency conversion change it). Change the constants at the top of `unit_economics.py` and re-run.
