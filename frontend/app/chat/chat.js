/**
 * Chat controller: sending, streaming a turn, stop / regenerate / edit /
 * retry, error-code handling, and loading a conversation from history.
 */
import { $, showScreen, newId } from '../dom.js';
import { state, set, pushHistory } from '../store.js';
import { streamChat, api, ApiError, NetworkError } from '../api.js';
import { announce, announceMessage } from '../a11y.js';
import { showToast } from '../toast.js';
import { savePendingDraft, showLoginPrompt, checkGuestStatus } from '../auth.js';
import { loadConversations, renderConversations, closeDrawer } from '../sidebar.js';
import { openPurchaseSheet, setBalance, renderBalance, loadCredits } from '../payments.js';
import { onSpeak, stopSpeaking } from '../tts.js';
import { openSourcesPanel, closeSourcesPanel } from './sources.js';
import { Composer } from './composer.js';
import { Thread } from './thread.js';
import { UserMessage, AssistantMessage, assistantFromHistory } from './message.js';

/** @type {Composer} */ let welcome;
/** @type {Composer} */ let composer;
/** @type {Thread} */ let thread;

/**
 * @typedef {{
 *   body: any, user: UserMessage|null, view: AssistantMessage|null,
 *   controller: AbortController|null, done: boolean, sawToken: boolean,
 *   savedId: string|null, saveFailed: boolean, referral: boolean,
 *   stopped: boolean, kind: 'send'|'regenerate'|'edit'
 * }} Turn
 */
/** @type {Turn|null} */
let turn = null;

const clientTz = (() => {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || null; } catch { return null; }
})();

/* ---------------- routing ---------------- */

export function setRoute(conversationId, { replace = false } = {}) {
    const path = conversationId ? `/c/${encodeURIComponent(conversationId)}` : '/';
    if (window.location.pathname === path) return;
    const method = replace ? 'replaceState' : 'pushState';
    try { window.history[method]({ conversationId }, '', path); } catch { /* sandboxed */ }
}

export function routeConversationId() {
    const match = /^\/c\/([^/?#]+)/.exec(window.location.pathname);
    return match ? decodeURIComponent(match[1]) : null;
}

/* ---------------- message context ---------------- */

async function copyText(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('Copied to clipboard');
    } catch {
        showToast('Failed to copy', { tone: 'error' });
    }
}

async function feedback(messageId, type, button, bar) {
    if (!messageId) { showToast('Cannot save feedback'); return; }
    const active = button.classList.contains('active');
    try {
        if (active) {
            await api.del(`/feedback/${encodeURIComponent(messageId)}`);
            button.classList.remove('active');
            button.setAttribute('aria-pressed', 'false');
        } else {
            bar.querySelectorAll('.action-btn.active').forEach((b) => { b.classList.remove('active'); b.setAttribute('aria-pressed', 'false'); });
            await api.post('/feedback', { message_id: messageId, feedback_type: type });
            button.classList.add('active');
            button.setAttribute('aria-pressed', 'true');
            announce(type === 'thumbs_up' ? 'Thanks for the feedback.' : 'Thanks. Your feedback helps improve answers.');
        }
    } catch {
        showToast('Could not save feedback', { tone: 'error' });
    }
}

/** @type {import('./message.js').MessageContext} */
const ctx = {
    onCopy: copyText,
    onSpeak,
    onFeedback: feedback,
    onRegenerate: () => regenerate(),
    onEdit: (view) => editMessage(view),
    onOpenSources: (items, index, trigger) => openSourcesPanel(items, index, trigger),
    onGrow: () => thread && thread.grew(),
};

/* ---------------- UI state ---------------- */

function setStreaming(streaming) {
    set({ streaming });
    document.body.dataset.streaming = String(streaming);
    composer.setBusy(streaming);
    welcome.setBusy(streaming);
    $('chatMessages').setAttribute('aria-busy', String(streaming));
}

function showChat() {
    showScreen('chatScreen');
}

function setReferral(visible) {
    $('referralNotice').classList.toggle('hidden', !visible);
    if (visible) announce('A human rabbi or counselor may be helpful for this question.');
}

function updateTitle() {
    const conv = state.conversations.find((c) => c.id === state.conversationId);
    $('chatTitle').textContent = (conv && (conv.title || conv.first_message)) || 'New conversation';
    document.title = conv && conv.title ? `${conv.title} | rebbe.dev` : 'rebbe.dev | Guided conversation';
}

/* ---------------- sending ---------------- */

async function createConversation() {
    try {
        const conversation = await api.post('/conversations', {});
        set({ conversationId: conversation.id, conversations: [conversation, ...state.conversations.filter((c) => c.id !== conversation.id)] });
        renderConversations();
        return conversation.id;
    } catch (error) {
        console.warn('Could not create conversation, continuing without persistence', error);
        return null;
    }
}

/** Entry point for both composers. */
export async function send(text, { fromWelcome = false } = {}) {
    if (state.streaming) return;
    if (!state.user) {
        savePendingDraft(text);
        showLoginPrompt();
        return;
    }
    stopSpeaking();
    if (fromWelcome) {
        welcome.clear();
        thread.clear();
        setReferral(false);
        showChat();
        $('chatTitle').textContent = 'New conversation';
        const id = await createConversation();
        if (id) { setRoute(id); composer.useDraftKey(id); }
    } else {
        composer.clear();
    }

    const user = new UserMessage(text, { ctx });
    thread.append(user.el);
    thread.scrollToBottom();
    if (!state.conversationId) pushHistory('user', text);
    runTurn({ message: text }, { user, kind: 'send' });
}

function buildBody(payload) {
    const body = {
        message: payload.message,
        session_id: state.sessionId,
        conversation_id: state.conversationId,
        request_id: newId(),
        client_tz: clientTz,
    };
    if (payload.regenerate) body.regenerate = true;
    if (payload.edit_message_id) body.edit_message_id = payload.edit_message_id;
    if (!state.conversationId) {
        // Guests: the server cannot load history, so send ours (capped).
        const history = [...state.history];
        if (history.length && history[history.length - 1].role === 'user' && history[history.length - 1].content === payload.message) history.pop();
        body.conversation_history = history;
    }
    return body;
}

/**
 * @param {{message:string, regenerate?:boolean, edit_message_id?:string}} payload
 * @param {{user?:UserMessage|null, kind:'send'|'regenerate'|'edit', body?:any}} options
 */
async function runTurn(payload, { user = null, kind, body = null }) {
    const view = new AssistantMessage({ ctx });
    thread.append(view.el);
    view.setStatus('Thinking…');
    thread.grew();

    /** @type {Turn} */
    const current = {
        body: body || buildBody(payload),
        user, view, kind,
        controller: new AbortController(),
        done: false, sawToken: false, savedId: null, saveFailed: false,
        referral: false, stopped: false,
    };
    turn = current;
    set({ crisisTurn: false });
    renderBalance();
    setStreaming(true);
    announce('Preparing a response.');

    try {
        await streamChat(current.body, {
            signal: current.controller.signal,
            onEvent: (event) => handleEvent(current, event),
        });
        if (!current.done) {
            if (current.sawToken) finishTurn(current, {});
            else throw new ApiError('No response received', { code: 'provider_unavailable' });
        }
    } catch (error) {
        if (current.done && !(error instanceof ApiError)) {
            // The answer is complete; a dropped post-`done` connection only
            // means no retraction will arrive.
        } else if (error && error.name === 'AbortError') {
            onStopped(current);
        } else {
            onTurnError(current, error);
        }
    } finally {
        if (turn === current) turn = null;
        if (!current.done) setStreaming(false);
    }
}

function handleEvent(current, raw) {
    const view = current.view;
    // v2 payloads may sit at the top level or under `data`; accept both.
    const event = raw.type !== 'token' && raw.type !== 'metadata' && raw.data && typeof raw.data === 'object' && !Array.isArray(raw.data)
        ? { ...raw.data, ...raw }
        : raw;
    switch (event.type) {
        case 'session':
            if (event.session_id) set({ sessionId: event.session_id });
            if (event.conversation_id && event.conversation_id !== state.conversationId) {
                set({ conversationId: event.conversation_id });
                setRoute(event.conversation_id, { replace: true });
            }
            if (event.user_message_id && current.user) current.user.setId(event.user_message_id);
            break;
        case 'status':
            view.setStatus(event.label || (event.stage === 'sources' ? 'Looking in the sources…' : 'Writing…'));
            break;
        case 'safety_resources': {
            // The latest card in a turn replaces any earlier one.
            const data = event;
            view.showSafety(data);
            set({ crisisTurn: true });
            renderBalance();
            announce(`${data.title || 'Support is available'}. Contact options are shown above the reply.`);
            break;
        }
        case 'metadata': {
            const meta = event.data || {};
            view.setMetadata(meta);
            current.referral = !!meta.requires_human_referral;
            break;
        }
        case 'token': {
            const text = typeof event.data === 'string' ? event.data : (event.text || (event.data && event.data.text) || '');
            if (text) { current.sawToken = true; view.appendToken(text); }
            break;
        }
        case 'citation':
            view.addCitation(event.n, event.source);
            break;
        case 'message_saved':
            current.savedId = event.message_id || null;
            if (event.user_message_id && current.user) current.user.setId(event.user_message_id);
            if (current.done && current.savedId) view.setId(current.savedId);
            break;
        case 'message_save_failed':
            current.saveFailed = true;
            break;
        case 'done':
            if (event.message_id) current.savedId = event.message_id;
            if (event.credits_remaining !== undefined && event.credits_remaining !== null) setBalance(event.credits_remaining);
            finishTurn(current, {});
            break;
        case 'retraction':
            view.retract(event.replacement || '', event.reason || '');
            announce("Part of this answer was withdrawn. The message has been updated.");
            break;
        case 'error':
            throw new ApiError(event.message || 'Something went wrong', {
                code: event.code || (event.message === 'guest_limit_reached' ? 'guest_limit_reached' : null),
                detail: event.detail,
                retryAfter: event.detail && event.detail.retry_after,
            });
        default:
            break;
    }
}

function finishTurn(current, { stopped = false } = {}) {
    if (current.done) return;
    current.done = true;
    current.view.finalize({ messageId: current.savedId, saveFailed: current.saveFailed, stopped });
    thread.markLast();
    if (!state.conversationId) pushHistory('assistant', current.view.content);
    setStreaming(false);
    if (!stopped) {
        announceMessage(current.view.plainText());
        setReferral(current.referral);
    }
    if (state.user) {
        loadConversations().then(updateTitle);
        if (!stopped && current.savedId === null && state.credits && !state.credits.unlimited) loadCredits();
    } else {
        checkGuestStatus();
    }
}

function onStopped(current) {
    current.stopped = true;
    if (current.view.hasText) {
        finishTurn(current, { stopped: true });
        announce('Stopped.');
    } else {
        current.view.showError({
            tone: 'info',
            title: 'Stopped before a reply',
            body: 'No credit is used when nothing was written.',
            actions: [{ label: 'Try again', icon: 'arrow-clockwise', primary: true, onClick: () => retry(current, { fresh: true }) }],
        });
        announce('Stopped.');
    }
    // The server refunds early stops; reflect the corrected balance.
    if (state.user) setTimeout(loadCredits, 1200);
}

/** Put a message back in the composer after the turn could not start. */
function withdrawTurn(current) {
    const text = current.body.message;
    current.view.remove();
    if (current.kind === 'send' && current.user) {
        current.user.el.remove();
        if (!state.conversationId && state.history.length && state.history[state.history.length - 1].role === 'user') {
            state.history = state.history.slice(0, -1);
        }
    }
    thread.markLast();
    if (current.kind === 'send') {
        if (!$('chatMessages').childElementCount) {
            showScreen('welcomeScreen');
            welcome.value = text;
            welcome.focus();
        } else {
            composer.value = text;
            composer.flushDraft();
        }
    }
    return text;
}

function countdown(view, seconds, current) {
    let remaining = Math.max(1, Math.round(seconds));
    const render = () => view.showError({
        tone: 'warning',
        title: "You're sending messages quickly",
        body: remaining > 0 ? `Take a breath. You can try again in ${remaining} second${remaining === 1 ? '' : 's'}.` : 'You can try again now.',
        actions: remaining > 0 ? [] : [{ label: 'Try again', icon: 'arrow-clockwise', primary: true, onClick: () => retry(current) }],
    });
    render();
    const timer = setInterval(() => {
        remaining -= 1;
        if (!document.contains(view.el)) { clearInterval(timer); return; }
        render();
        if (remaining <= 0) clearInterval(timer);
    }, 1000);
}

function onTurnError(current, error) {
    const code = error instanceof ApiError ? error.code : (error instanceof NetworkError ? 'network' : 'internal');
    const view = current.view;
    const partial = view.hasText;
    if (partial) finishTurn(current, { stopped: true });
    setStreaming(false);

    switch (code) {
        case 'no_credits': {
            const text = partial ? current.body.message : withdrawTurn(current);
            openPurchaseSheet({
                reason: "You're out of credits. Your message is saved; add credits to send it.",
                onPurchased: () => {
                    showToast('Credits added. Press Enter to send.');
                    const target = document.body.dataset.screen === 'welcomeScreen' ? welcome : composer;
                    if (!target.value) target.value = text;
                    target.focus();
                },
            });
            announce("You're out of credits. Your message is saved.");
            return;
        }
        case 'guest_limit_reached':
        case 'unauthenticated': {
            const text = partial ? current.body.message : withdrawTurn(current);
            savePendingDraft(text);
            showLoginPrompt(code === 'unauthenticated' ? 'Please sign in again to keep chatting' : 'Sign in to keep the conversation going');
            return;
        }
        case 'invalid_input': {
            if (!partial) withdrawTurn(current);
            showToast(error.message && !/^Request failed/.test(error.message) ? error.message : 'That message could not be sent. Messages can be up to 4,000 characters.', { tone: 'error', duration: 4000 });
            return;
        }
        case 'rate_limited':
            countdown(view, error.retryAfter || 20, current);
            return;
        case 'access_restricted':
            view.showError({ title: 'This conversation is unavailable', body: error.message || 'Access to chat is restricted for this account.' });
            return;
        case 'timeout':
            view.showError({
                title: 'Request timed out, please try again.',
                body: 'The reply took too long to start.',
                actions: [{ label: 'Retry', icon: 'arrow-clockwise', primary: true, onClick: () => retry(current) }],
            });
            announce('The request timed out. Please try again.');
            return;
        case 'network':
            view.showError({
                title: navigator.onLine === false ? "You're offline" : 'Connection lost',
                body: partial ? 'The reply was cut off. Retrying will not charge you twice.' : 'Check your connection, then retry. You will not be charged twice.',
                actions: [{ label: 'Retry', icon: 'arrow-clockwise', primary: true, onClick: () => retry(current) }],
            });
            announce('The response could not be completed. Please try again.');
            return;
        case 'provider_unavailable':
        default:
            view.showError({
                title: code === 'provider_unavailable' ? 'The answer service is busy right now' : "Something went wrong on our side",
                body: 'Please try again in a moment. You will not be charged twice.',
                actions: [{ label: 'Retry', icon: 'arrow-clockwise', primary: true, onClick: () => retry(current) }],
            });
            announce('The response could not be completed. Please try again.');
    }
}

/** Re-run a failed turn with the same request_id (idempotent server-side). */
function retry(current, { fresh = false } = {}) {
    if (state.streaming) return;
    if (current.view.hasText) current.view.clearError();
    else current.view.remove();
    const body = fresh ? { ...current.body, request_id: newId() } : current.body;
    if (current.view.hasText) {
        // Partial answer kept: ask for a fresh one in its place.
        current.view.remove();
        runTurn({ message: body.message, regenerate: true }, { kind: 'regenerate' });
        return;
    }
    runTurn({ message: body.message }, { user: current.user, kind: current.kind, body });
}

/* ---------------- regenerate / edit ---------------- */

function lastOf(selector) {
    const all = $('chatMessages').querySelectorAll(selector);
    return all[all.length - 1] || null;
}

export function regenerate() {
    if (state.streaming) return;
    const lastUser = lastOf('.message.user');
    const lastAssistant = lastOf('.message.assistant');
    if (!lastUser) return;
    const text = lastUser.querySelector('.message-content').textContent;
    if (lastAssistant) lastAssistant.remove();
    if (!state.conversationId && state.history.length && state.history[state.history.length - 1].role === 'assistant') {
        state.history = state.history.slice(0, -1);
    }
    setReferral(false);
    runTurn({ message: text, regenerate: true }, { kind: 'regenerate' });
}

async function lastUserMessageId() {
    if (!state.conversationId) return null;
    try {
        const data = await api.get(`/conversations/${encodeURIComponent(state.conversationId)}`);
        const users = (data.messages || []).filter((m) => m.role === 'user');
        return users.length ? users[users.length - 1].id : null;
    } catch {
        return null;
    }
}

async function editMessage(view) {
    if (state.streaming) return;
    const next = await view.beginEdit();
    if (!next || next === view.text) return;

    let editId = view.id;
    if (!editId && state.conversationId) editId = await lastUserMessageId();
    if (state.conversationId && !editId) {
        showToast('This message cannot be edited yet. Try again in a moment.', { tone: 'error' });
        return;
    }
    // Drop the edited message's reply and everything after it.
    let node = view.el.nextElementSibling;
    while (node) { const nextNode = node.nextElementSibling; node.remove(); node = nextNode; }
    view.text = next;
    view.content.textContent = next;
    setReferral(false);
    if (!state.conversationId) {
        const history = [...state.history];
        while (history.length && history[history.length - 1].role === 'assistant') history.pop();
        if (history.length) history.pop();
        state.history = [...history, { role: 'user', content: next }];
    }
    thread.markLast();
    runTurn({ message: next, edit_message_id: editId || undefined }, { user: view, kind: 'edit' });
}

/* ---------------- stop / navigation ---------------- */

export function stop() {
    if (turn && turn.controller && !turn.done) turn.controller.abort();
}

export function startNewConversation({ push = true } = {}) {
    stop();
    stopSpeaking();
    closeSourcesPanel();
    thread.savePosition(state.conversationId);
    set({ conversationId: null, sessionId: null, history: [] });
    thread.clear();
    setReferral(false);
    showScreen('welcomeScreen');
    renderConversations();
    closeDrawer();
    composer.useDraftKey('chat-new');
    document.title = 'rebbe.dev | Guided conversation';
    if (push) setRoute(null);
    requestAnimationFrame(() => welcome.focus());
}

export async function openConversation(conversationId, { push = true } = {}) {
    if (!conversationId) return;
    if (conversationId === state.conversationId && document.body.dataset.screen === 'chatScreen') {
        closeDrawer();
        return;
    }
    stop();
    stopSpeaking();
    closeSourcesPanel();
    thread.savePosition(state.conversationId);
    let data;
    try {
        data = await api.get(`/conversations/${encodeURIComponent(conversationId)}`);
    } catch (error) {
        showToast(error.status === 404 ? 'That conversation could not be found.' : 'Could not open that conversation.', { tone: 'error' });
        if (error.status === 404) startNewConversation({ push: false });
        if (error.status === 404) setRoute(null, { replace: true });
        return;
    }
    set({ conversationId, sessionId: null, history: [] });
    thread.clear();
    for (const message of data.messages || []) {
        if (message.role === 'user') {
            thread.append(new UserMessage(message.content, { id: message.id, date: message.created_at ? new Date(message.created_at) : new Date(), ctx }).el);
        } else if (message.role === 'assistant') {
            thread.append(assistantFromHistory(message, ctx).el);
        }
    }
    thread.markLast();
    const last = (data.messages || []).filter((m) => m.role === 'assistant').pop();
    setReferral(!!(last && last.metadata && last.metadata.requires_human_referral));
    if (data.title && !state.conversations.some((c) => c.id === conversationId)) {
        set({ conversations: [{ id: conversationId, title: data.title, updated_at: data.updated_at }, ...state.conversations] });
    }
    showChat();
    updateTitle();
    if (data.title) $('chatTitle').textContent = data.title;
    renderConversations();
    closeDrawer();
    composer.useDraftKey(conversationId);
    thread.restorePosition(conversationId);
    if (push) setRoute(conversationId);
}

/* ---------------- init ---------------- */

export function initChat() {
    thread = new Thread($('chatScroller'), $('chatMessages'), $('jumpLatest'));
    welcome = new Composer({
        textarea: $('messageInput'),
        sendBtn: $('sendBtn'),
        maxHeight: 240,
        onSubmit: (text) => send(text, { fromWelcome: true }),
    });
    composer = new Composer({
        textarea: $('chatInput'),
        sendBtn: $('chatSendBtn'),
        stopBtn: $('stopBtn'),
        maxHeight: 200,
        onSubmit: (text) => send(text),
        onStop: stop,
    });
    welcome.useDraftKey('new');
    composer.useDraftKey('chat-new');

    document.querySelectorAll('.suggestion-chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            welcome.value = chip.dataset.prompt;
            welcome.flushDraft();
            welcome.focus();
        });
    });
    return { welcome, composer, thread };
}

export const composers = () => ({ welcome, composer });
