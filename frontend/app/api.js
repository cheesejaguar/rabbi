/**
 * HTTP + Server-Sent Events client.
 *
 * - `api.*` wraps fetch with JSON handling and a typed ApiError.
 * - `streamChat()` POSTs to /api/chat/stream and parses the SSE body
 *   incrementally, handing each event object to `onEvent`. It is abortable
 *   (AbortController) and safe to call again with the same request_id: the
 *   server treats that as an idempotent retry and does not charge twice.
 */

const API = '/api';

export class ApiError extends Error {
    /**
     * @param {string} message
     * @param {{status?:number, code?:string, detail?:any, retryAfter?:number|null}} [info]
     */
    constructor(message, info = {}) {
        super(message);
        this.name = 'ApiError';
        this.status = info.status || 0;
        this.code = info.code || null;
        this.detail = info.detail;
        this.retryAfter = info.retryAfter ?? null;
    }
}

/** Raised when the request never reached the server (offline, DNS, reset). */
export class NetworkError extends Error {
    constructor(message = 'Network error') {
        super(message);
        this.name = 'NetworkError';
    }
}

const STATUS_CODES = {
    401: 'unauthenticated',
    402: 'no_credits',
    413: 'invalid_input',
    422: 'invalid_input',
    429: 'rate_limited',
    502: 'provider_unavailable',
    503: 'provider_unavailable',
    504: 'provider_unavailable',
};

function retryAfterSeconds(response, body) {
    const fromBody = body && (body.retry_after ?? (body.detail && body.detail.retry_after));
    if (Number.isFinite(Number(fromBody)) && fromBody !== null) return Number(fromBody);
    const header = response.headers.get('Retry-After');
    if (!header) return null;
    const seconds = Number(header);
    if (Number.isFinite(seconds)) return seconds;
    const date = Date.parse(header);
    return Number.isFinite(date) ? Math.max(0, Math.round((date - Date.now()) / 1000)) : null;
}

async function errorFromResponse(response) {
    let body = null;
    try { body = await response.json(); } catch { /* non-JSON error body */ }
    const detail = body && body.detail;
    const code = (body && body.code)
        || (detail && typeof detail === 'object' && detail.code)
        || STATUS_CODES[response.status]
        || (response.status >= 500 ? 'internal' : null);
    const message = (typeof detail === 'string' && detail)
        || (detail && typeof detail === 'object' && (detail.message || detail.detail))
        || (body && body.message)
        || `Request failed (${response.status})`;
    return new ApiError(message, {
        status: response.status,
        code,
        detail,
        retryAfter: retryAfterSeconds(response, body),
    });
}

/**
 * @param {string} path  path below /api (e.g. "/credits") or an absolute path
 * @param {RequestInit & {json?: any}} [options]
 */
export async function request(path, options = {}) {
    const url = path.startsWith('/api') || path.startsWith('/auth') ? path : `${API}${path}`;
    const init = { credentials: 'include', ...options };
    if ('json' in options) {
        init.body = JSON.stringify(options.json);
        init.headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
        delete init.json;
    }
    let response;
    try {
        response = await fetch(url, init);
    } catch (error) {
        if (error && error.name === 'AbortError') throw error;
        throw new NetworkError(error && error.message);
    }
    if (!response.ok) throw await errorFromResponse(response);
    if (response.status === 204) return null;
    const type = response.headers.get('content-type') || '';
    return type.includes('json') ? response.json() : response;
}

export const api = {
    get: (path, options) => request(path, { method: 'GET', ...options }),
    post: (path, json, options) => request(path, { method: 'POST', json, ...options }),
    put: (path, json, options) => request(path, { method: 'PUT', json, ...options }),
    patch: (path, json, options) => request(path, { method: 'PATCH', json, ...options }),
    del: (path, json, options) => request(path, json === undefined
        ? { method: 'DELETE', ...options }
        : { method: 'DELETE', json, ...options }),
};

/**
 * Incremental SSE parser. Feed decoded text; complete events come back.
 * Handles CRLF, multi-line `data:` fields, comments, and `[DONE]`.
 */
export function createSSEParser(onEvent) {
    let buffer = '';
    let dataLines = [];
    let eventName = null;

    const dispatch = () => {
        if (!dataLines.length) { eventName = null; return; }
        const raw = dataLines.join('\n');
        dataLines = [];
        const name = eventName;
        eventName = null;
        if (raw === '[DONE]') { onEvent({ type: 'done' }); return; }
        let payload;
        try {
            payload = JSON.parse(raw);
        } catch {
            return; // A malformed frame must not abort the stream.
        }
        if (payload && typeof payload === 'object') {
            if (!payload.type && name) payload.type = name;
            onEvent(payload);
        }
    };

    const line = (text) => {
        if (text === '') { dispatch(); return; }
        if (text.startsWith(':')) return;
        const colon = text.indexOf(':');
        const field = colon === -1 ? text : text.slice(0, colon);
        let value = colon === -1 ? '' : text.slice(colon + 1);
        if (value.startsWith(' ')) value = value.slice(1);
        if (field === 'data') dataLines.push(value);
        else if (field === 'event') eventName = value;
    };

    return {
        push(chunk) {
            buffer += chunk;
            let index;
            while ((index = buffer.search(/\r\n|\r|\n/)) !== -1) {
                const text = buffer.slice(0, index);
                const newline = buffer[index] === '\r' && buffer[index + 1] === '\n' ? 2 : 1;
                buffer = buffer.slice(index + newline);
                line(text);
            }
        },
        end() {
            if (buffer) { line(buffer); buffer = ''; }
            dispatch();
        },
    };
}

/**
 * POST a chat turn and stream its events.
 * @param {object} body  request body per API_CONTRACT_V2
 * @param {{signal?: AbortSignal, onEvent: (event:any)=>void, firstByteTimeoutMs?: number}} options
 * @returns {Promise<void>} resolves when the stream closes
 */
export async function streamChat(body, { signal, onEvent, firstByteTimeoutMs = 90000 }) {
    // A hung backend gets a watchdog until the first byte arrives; a slow
    // but working stream is never cut off once data is flowing.
    const watchdog = new AbortController();
    const relay = () => watchdog.abort(signal.reason);
    if (signal) {
        if (signal.aborted) relay();
        else signal.addEventListener('abort', relay, { once: true });
    }
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; watchdog.abort(); }, firstByteTimeoutMs);

    let response;
    try {
        response = await fetch(`${API}/chat/stream`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
            body: JSON.stringify(body),
            signal: watchdog.signal,
        });
    } catch (error) {
        clearTimeout(timer);
        if (timedOut) throw new ApiError('The request timed out.', { code: 'timeout' });
        if (error && error.name === 'AbortError') throw error;
        throw new NetworkError(error && error.message);
    }

    if (!response.ok) {
        clearTimeout(timer);
        throw await errorFromResponse(response);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parser = createSSEParser(onEvent);
    let started = false;
    try {
        while (true) {
            const { done, value } = await reader.read();
            if (!started) { started = true; clearTimeout(timer); }
            if (done) break;
            parser.push(decoder.decode(value, { stream: true }));
        }
        parser.push(decoder.decode());
        parser.end();
    } catch (error) {
        clearTimeout(timer);
        if (error instanceof ApiError) throw error; // an `error` event raised by onEvent
        if (timedOut) throw new ApiError('The request timed out.', { code: 'timeout' });
        if (error && error.name === 'AbortError') throw error;
        if (signal && signal.aborted) {
            const abort = new Error('Aborted');
            abort.name = 'AbortError';
            throw abort;
        }
        throw new NetworkError(error && error.message);
    } finally {
        clearTimeout(timer);
        if (signal) signal.removeEventListener('abort', relay);
    }
}
