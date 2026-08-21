# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary audience is Jewishly curious adults across observance levels. They may be beginning a practice, returning to Jewish learning, comparing traditions, or looking for a thoughtful way into a personal question. They need context and usable guidance without being asked to present as experts or to adopt a particular level of observance.

Administrators are a secondary audience. They review operations, feedback, safety signals, purchases, sponsorships, costs, and audit activity without changing the public product's theological or safety boundaries.

## Product Purpose

rebbe.dev helps people explore Jewish thought, practice, law, ethics, and spirituality through a source-aware guided conversation. Success means that a person leaves with a clearer map of the question, relevant sources and perspectives, a humane next step, and an honest understanding of when a rabbi or other qualified human should be involved.

## Positioning

rebbe.dev is a Jewish guidance companion, not an automated rabbinic authority. Its distinctive mechanism combines pastoral context, halachic reasoning, ethical review, and an appropriate final voice into one response. It can surface a landscape of Jewish sources and viewpoints while keeping the boundary between guidance and binding psak explicit.

## Operating Context

People use the product in a browser to ask a question, read a streamed response, examine source references, continue a conversation, listen to a response, leave feedback, manage a profile, and read a current d'var Torah. Signed-in users retain conversation history and can purchase additional credits. A d'var Torah may include a paid dedication. Calendar notices provide contextual awareness but do not disable the product.

The public landing page is the anonymous entry point. FastAPI serves either that page or the signed-in conversational application at the root according to authentication state. The internal admin application remains role-protected and excluded from indexing.

## Capabilities and Constraints

- The production frontend is plain HTML, CSS, and JavaScript with no build step.
- FastAPI routing, `/static/*`, `/admin`, `/auth/*`, the authentication `postMessage` contract, and Vercel route ordering must remain compatible.
- Existing API payloads, server-sent event types, analytics event names, payment request bodies, and the twenty-message conversation-history cap are stable contracts.
- Backend enum values for denominations, `credits_10`, `credits_25`, sponsorship tiers, and dedication types must remain unchanged.
- Credit packages are ten credits for $1.00 and twenty-five credits for $2.00.
- The response pipeline includes pastoral context, halachic reasoning, ethical review, and final voice. These are system processes, not guarantees of correctness.
- Retrieved source matches and model-knowledge citations must remain clearly distinguishable. A retrieved match is not a claim-level verification guarantee.
- The product provides guidance, not binding psak. Human referral remains a foundational safety behavior.
- Conversation access is scoped for ordinary users, while authorized administrators may review content for operations, moderation, and safety. The interface must not make an absolute privacy promise.
- No database migration or new backend product endpoint is part of this redesign.

## Brand Commitments

The product name and domain remain `rebbe.dev`. The voice is thoughtful, plainspoken, welcoming across observance levels, intellectually serious, and candid about limits. Product language must not imply automated rabbinic authority, certainty, or a promise that the service observes Shabbat by shutting down.

The approved identity is Braided Light. Its mark is a reduced lowercase `r` formed from four interlacing strands, conceptually derived from a braided Havdalah wick: context, halachic reasoning, ethical review, and voice become one response. This identity replaces the existing Star of David mark across public, signed-in, admin, favicon, and social surfaces.

## Evidence on Hand

- The runnable application and its API contracts are present in `backend/` and `frontend/`.
- The four-stage reasoning mechanism is documented in `README.md` and implemented in `backend/app/agents/`.
- Current pricing and sponsorship tiers are defined in `backend/app/payments.py`.
- Public-page and admin authorization behavior is covered by the existing backend test suite.
- The product has no supplied testimonials, public usage figures, terms of service, independent accuracy study, or substantiated commercial performance claims. The privacy policy is grounded in the implemented data flows and must remain current as those flows change.

## Product Principles

1. Show the reasoning path and the limits of the answer.
2. Welcome people at different levels of knowledge and observance without flattening meaningful differences.
3. Keep sources legible, distinguish evidence types, and avoid stronger verification claims than the system supports.
4. Protect human dignity and make referral to qualified people a normal part of good guidance.
5. Preserve product truth and operational compatibility before adding novelty.

## Accessibility & Inclusion

All public, conversational, reading, and admin surfaces target WCAG 2.2 AA. They support keyboard operation, visible focus, persistent labels, screen-reader live updates, reduced motion, 200 percent zoom, minimum 44px action targets, and bidirectional content with `dir="auto"`. The visual system follows system light or dark preference on first visit and preserves a manual theme choice.
