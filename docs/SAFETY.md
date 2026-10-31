# rebbe.dev safety system

This is how pipeline v2 protects users and the service. The design is in `docs/REWRITE_PLAN.md` §3; this page describes what the code does and how to operate it.

## Layers (in request order)

| Layer | Code | What it does | If it fails |
|---|---|---|---|
| 0. Deterministic gate | `ratelimit.py`, `chat/endpoint.py` | Postgres-backed per-user/IP rate limits shared by every instance; guest caps (3 per device, IP cap, daily free-tier dollar budget); IP penalty box after repeated manipulation attempts; input bounds (4,000 chars, control/zero-width stripping); server-loaded history for signed-in users; idempotent credit charge per `request_id` | Falls back to in-process counters (availability over strictness); the credit check fails **closed** |
| 0b. Crisis lexicon floor | `safety/lexicon.py` | English/Hebrew/transliterated patterns for first-person suicidal intent, self-harm, abuse disclosure, harm to others. A match sends the resource card **before any model call** | Cannot fail: pure regex |
| 1. Safety classifier | `safety/classifier.py` (Claude Haiku 5.5, structured output) | Mode, question type, emotion, eight 0–3 risk scores, search keywords | Timeout or error → "unavailable" → counseling overlay plus a support card if the topic is sensitive (fails safe, not closed) |
| 2. Policy router | `safety/policy.py` (pure function) | Maps lexicon and classifier output to card level, overlays, effort, retrieval, charge, and admin alert | n/a |
| 3. Constitution | `prompts/constitution.md` and `prompts/__init__.py` overlays | The four v1 agents' values as one frozen, cached system prompt; per-turn safety overlays as a mid-conversation system message | A refusal with no text gets a safe static reply; if the gateway rejects the full request shape, a compatible shape is used automatically |
| 4. Post-stream audit | `safety/audit.py` (Haiku) | Grades every answer. `concern` → admin queue only for harm-related issues (`REVIEW_ISSUES`; "missing safety care" only when the turn had a risk flag); quality-only notes such as psak wording or citations are stored as `pass`; `severe` → retraction event, stored text replaced (original kept for review), admin alert | Audit error → stored as `available: false` and the answer is kept |
| 5. Humans | `safety/alerts.py`, `/api/admin/safety-events`, `/api/admin/flagged` | Webhook alert (no message text) for crisis, abuse, harm, and retraction; review queues including guest turns. The crisis queue lists crisis/abuse turns, harm-to-others flags, retractions, and harm-related audit concerns; counseling mode, `vulnerability_detected` and human-referral hints alone do not queue a message | Alerting is best-effort with a 3 s timeout |

**The crisis floor runs before every other check.** Rate limits, IP blocks, input-length errors, walls, and credit errors can't suppress the resource card. An overlong crisis message is truncated and answered rather than rejected.

**Walls never block a crisis turn.** If a guest is over the limit or a user has no credits, the endpoint still checks the message (lexicon, then classifier). A possible crisis or abuse disclosure is answered, free of charge. Crisis and abuse turns are never charged.

## Crisis resources

Static, versioned content lives in `safety/resources.py` (`RESOURCES_VERSION`). The region comes from the client's IANA time zone, falling back to `Accept-Language`. A zone outside the covered regions gets the international card ("your local emergency number" plus worldwide directories), never US-only numbers. Ordering rule: emergency number and 24/7 general lines first, then community services (several of which are referral or limited-hours lines, not crisis lines).

Verification (2026-10-31), against each organization's own site unless noted:

| Entry | Verified on | Notes |
|---|---|---|
| 988 Suicide & Crisis Lifeline (US) | 988lifeline.org | call/text 988, chat |
| Crisis Text Line US 741741 / IE 50808 | crisistextline.org | |
| Shout UK 85258 | crisistextline.org partner listing | keyword SHOUT |
| 9-8-8 Canada | 988.ca | |
| Samaritans 116 123 | samaritans.org | UK online chat currently unavailable |
| Lifeline Australia 13 11 14 | lifeline.org.au | |
| ERAN 1201 (Israel) | Israel Trauma Coalition and Ministry of Health pages (eran.org.il blocked automated fetch) | mainly Hebrew |
| Sahar (Israel) | sahar.org.il | hours limited |
| NATAL *3362 | natal.org.il/en/contact-us | Israeli short code |
| Israel Trauma Coalition | israeltraumacoalition.org | |
| Chai Lifeline Crisis 855-327-4747 | chailifeline.org/crisis | |
| Relief Resources 718-431-9501 | reliefhelp.org | referral, not crisis |
| Jewish Family Services locator | networkjhsa.org | |
| Jami (UK) 020 8458 2223 | search-indexed jamiuk.org | crisis: text "Jami" to 85258 |
| National DV Hotline 800-799-7233 / text START to 88788 | referenced by Shalom Task Force as its after-hours line | **re-verify the text keyword on thehotline.org** |
| Shalom Task Force 888-883-2323 | shalomtaskforce.org/hotline | limited hours |
| Amudim 646-517-0222 / 02-374-0175 | amudim.org/contact | |
| UK National DA Helpline 0808 2000 247 | referenced by Jewish Women's Aid as out-of-hours | |
| Jewish Women's Aid 0808 801 0500 | jwa.org.uk | limited hours |
| Trevor Project, Teen Line | thetrevorproject.org, didihirsch.org/teenline | youth card |
| Kids Help Phone (CA) | kidshelpphone.ca | youth card |
| Find A Helpline, Befrienders Worldwide | well-known international directories | shown for regions without a dedicated list ("INTL": time zones outside the US, Canada, UK, Ireland, Israel, Australia). **Re-verify before launch.** |

Not included (could not be verified): Childline UK, Jewish Board DV line, BeWell regional lines, NATAL 1800-363-363. CST (UK, 0800 032 3263), ADL incident reporting, and the Secure Community Network duty desk (844-726-3375) were verified as **antisemitism incident** resources. They are not crisis lines and are not shown on the crisis card.

Re-verify every quarter, bump `RESOURCES_VERSION`, and have a human approve any change.

## Evals

`backend/evals/dataset.jsonl` holds about 100 labelled prompts: direct and veiled self-harm (EN/HE), abuse, harm to others, scholarly sensitive topics, ordinary halacha and learning, personal struggles, jailbreaks, hate, off-scope, minors, and medical. Run `uv run python backend/evals/run_evals.py --offline` (free; also enforced in CI by `test_v2_safety.py`), `--classifier` (about $0.01), or `--full` (about $2–3; writes answers to `backend/evals/out/` for human review). Gates: crisis/abuse card recall ≥ 99%, false crisis cards on benign prompts ≤ 3%, special routing ≥ 90%, zero severe audits.

Grow the set from real flagged traffic (anonymized) and keep crisis recall as the deciding metric.

## Independent review

A separate review pass over v2 (2026-10-31) found 14 defects, including two high-severity safety gaps: early exits that skipped the crisis floor, and a wall override that ignored crisis follow-ups. All 14 are fixed, with regression tests in `backend/tests/test_v2_pipeline.py`.

## Operating checklist

- Set `ADMIN_ALERT_WEBHOOK_URL` before launch, and keep someone on call for alerts.
- Review the `/admin` Crisis queue daily. It shows safety events (including guest turns), today's free-tier spend, and flagged or withdrawn answers.
- Run `--classifier` evals after any change to the prompt, classifier, or model, and `--full` before a release.
- Watch the free-tier spend in the safety-events response (`free_tier_spend_today_usd`).
