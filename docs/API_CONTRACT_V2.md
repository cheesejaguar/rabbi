# API & SSE contract (pipeline v2)

v2 is **additive**. Every v1 event and field keeps its shape, so an old client keeps working.

## `POST /api/chat/stream`

Request body (JSON):

| Field | Type | Notes |
|---|---|---|
| `message` | string, 1–4000 chars | Required. Messages over 4000 chars get `error` with code `invalid_input`. |
| `conversation_id` | string? | Signed-in users. When present, the server loads history from the DB and ignores `conversation_history`. |
| `conversation_history` | `[{role, content}]` | Guests only (≤20 turns used). |
| `session_id` | string? | Unchanged. |
| `request_id` | string? (≤64) | Client-generated UUID, echoed in `session` and logs for correlation. It is not a billing key: a failed turn is refunded automatically, so retrying after a failure costs one credit in total. |
| `regenerate` | bool, default false | Deletes the conversation's trailing assistant message and answers the last user message again. `message` must equal that user message. |
| `edit_message_id` | string? | Deletes this user message and everything after it, then answers `message` as the replacement. |
| `client_tz` | string? | IANA tz, used to choose region-appropriate crisis resources. |

Response: `text/event-stream`. Each frame is `data: <json>\n\n`. Events arrive in this order (any may be skipped):

| `type` | Payload | Meaning |
|---|---|---|
| `session` | `{session_id, conversation_id, request_id}` | Always first |
| `status` | `{stage: "safety"\|"sources"\|"writing", label}` | Progress line shown in the "thinking" shimmer |
| `safety_resources` | `{level: "crisis"\|"abuse"\|"support", title, message, resources: [{name, description, phone?, sms?, chat_url?, url, region, hours?}]}` | **Render before any tokens, prominently, and do not let the user dismiss it during the turn.** Server-authored static content. |
| `metadata` | v1 shape: `{requires_human_referral, pastoral_mode, question_type, vulnerability_detected, emotional_state, crisis_indicators?, sources:[...], rag_used, pipeline: "v2"}` | Before the first token |
| `token` | `{data: "<text>"}` | Streamed text (markdown) |
| `citation` | `{n, source: {title, ref, url?, excerpt, kind: "library"}}` | The text streamed just before this event is supported by source `n`. Render a superscript `[n]` at the current position. `n` is 1-based and stable within the message. |
| `metrics` | v1 shape | After the last token |
| `message_saved` | `{message_id}` | Signed-in users |
| `message_save_failed` | `{}` | Unchanged |
| `done` | `{message_id?, credits_remaining?, charged: bool}` | Stream complete. `charged=false` for crisis turns and failures. |
| `retraction` | `{message_id?, reason, replacement}` | Rare. Replace the message body with `replacement` and show a notice. May arrive after `done` while the stream is still open, or as `retracted` on a later load (see below). |
| `error` | `{message, code?, detail?}` | `code` ∈ `invalid_input`, `rate_limited`, `guest_limit_reached`, `no_credits`, `access_restricted`, `provider_unavailable`, `internal`. v1 clients read `message`; v2 clients branch on `code`. |

**Cancellation:** the client aborts the fetch (AbortController). If no tokens were delivered, the server refunds the credit.

## Messages

`GET /api/conversations/{id}/messages` messages gain these optional fields: `metadata.sources` (citation list), `metadata.citations` (`[{n, offset}]`, the character offset in `content` where marker `n` goes), `metadata.safety_resources` (same object as the SSE event), `metadata.retracted` (bool), and `metadata.retraction_reason`.

## Other new endpoints

| Method / path | Purpose |
|---|---|
| `GET /api/payments/packages` | Unchanged shape. New ids `credits_55`, `credits_160`, `credits_400` with `display_price`, plus `"recommended": true` on one. Legacy ids are not returned but remain valid in history. |
| `GET /api/account/export` | JSON download of the user's profile, conversations, and messages |
| `DELETE /api/account` | Body `{confirm: "DELETE"}`. Deletes the user and cascades; clears the session. |
| `GET /terms` | Terms of Service page (public) |
| `POST /api/speak` | Unchanged request. Premium voice costs `TTS_CREDIT_COST` credits (8 by default) unless the message was already voiced. Returns 402 with `{detail, code: "no_credits"}` when the balance is too low. Clients should default to browser `speechSynthesis` and offer premium voice as an explicit choice. |
| `GET /api/credits` | Adds `tts_credit_cost` |
