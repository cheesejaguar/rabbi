/**
 * Message elements: the user bubble and the assistant answer, with its
 * safety card, thinking shimmer, streamed markdown body, citation markers,
 * sources footer, error states, and action toolbar.
 */
import { h, icon, formatTime } from '../dom.js';
import { StreamingMarkdown, renderMarkdown, withCitationMarkers } from './markdown.js';
import { buildSourceItems, sourcesFooter } from './sources.js';

/**
 * Callbacks the chat controller supplies to every message.
 * @typedef {{
 *   onCopy:(text:string)=>void,
 *   onSpeak:(button:HTMLElement, text:string, messageId:string|null)=>void,
 *   onFeedback:(messageId:string|null, type:string, button:HTMLElement, bar:HTMLElement)=>void,
 *   onRegenerate:()=>void,
 *   onEdit:(view:UserMessage)=>void,
 *   onOpenSources:(items:any[], index:number, trigger:HTMLElement)=>void,
 *   onGrow:()=>void,
 * }} MessageContext
 */

function actionButton(action, label, iconName, extra = {}) {
    return h('button', {
        class: `action-btn ${extra.className || ''}`.trim(),
        type: 'button',
        'aria-label': label,
        title: label,
        dataset: { action },
        ...(extra.attrs || {}),
    }, icon(iconName), extra.text ? h('span', { class: 'action-text', text: extra.text }) : null);
}

/* ---------------- User ---------------- */

export class UserMessage {
    /**
     * @param {string} text
     * @param {{id?:string|null, date?:Date, ctx:MessageContext}} options
     */
    constructor(text, { id = null, date = new Date(), ctx }) {
        this.text = text;
        this.id = id;
        this.ctx = ctx;
        this.el = h('div', { class: 'message user' });
        if (id) this.el.dataset.messageId = id;
        this.content = h('div', { class: 'message-content', dir: 'auto', text });
        this.actions = h('div', { class: 'message-actions user-actions' },
            actionButton('copy', 'Copy message', 'copy'),
            actionButton('edit', 'Edit message', 'pencil-simple', { className: 'edit-btn' }));
        this.actions.addEventListener('click', (event) => {
            const button = event.target.closest('[data-action]');
            if (!button) return;
            if (button.dataset.action === 'copy') ctx.onCopy(this.text);
            if (button.dataset.action === 'edit') ctx.onEdit(this);
        });
        this.el.append(this.content, this.actions);
        this.el.title = formatTime(date);
    }

    setId(id) {
        this.id = id;
        if (id) this.el.dataset.messageId = id;
    }

    /**
     * Swap the bubble for an inline editor. Resolves with the new text, or
     * null when the edit is cancelled.
     * @returns {Promise<string|null>}
     */
    beginEdit() {
        return new Promise((resolve) => {
            this.el.classList.add('editing');
            const field = h('textarea', { class: 'edit-input', dir: 'auto', rows: '3', maxlength: '4000', 'aria-label': 'Edit your message' });
            field.value = this.text;
            const cancel = h('button', { class: 'btn btn-quiet btn-sm', type: 'button', text: 'Cancel' });
            const save = h('button', { class: 'btn btn-primary btn-sm', type: 'button', text: 'Send' });
            const editor = h('div', { class: 'edit-box' }, field, h('div', { class: 'edit-actions' }, cancel, save));
            this.content.replaceWith(editor);
            this.actions.hidden = true;

            const fit = () => { field.style.height = 'auto'; field.style.height = Math.min(field.scrollHeight, 320) + 'px'; };
            const finish = (value) => {
                editor.replaceWith(this.content);
                this.actions.hidden = false;
                this.el.classList.remove('editing');
                resolve(value);
            };
            field.addEventListener('input', () => { fit(); save.disabled = !field.value.trim(); });
            field.addEventListener('keydown', (event) => {
                if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); finish(null); }
                if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
                    event.preventDefault();
                    if (field.value.trim()) finish(field.value.trim());
                }
            });
            cancel.addEventListener('click', () => finish(null));
            save.addEventListener('click', () => { if (field.value.trim()) finish(field.value.trim()); });
            requestAnimationFrame(() => { fit(); field.focus(); field.setSelectionRange(field.value.length, field.value.length); });
        });
    }
}

/* ---------------- Safety card ---------------- */

const digits = (value) => String(value || '').replace(/[^\d+]/g, '');

function smsLink(sms) {
    const text = String(sms || '').trim();
    const keyword = /^(.+?)\s+to\s+([\d+\s-]+)$/i.exec(text);
    if (keyword) {
        return { href: `sms:${digits(keyword[2])}?&body=${encodeURIComponent(keyword[1].trim())}`, label: `Text ${keyword[1].trim()} to ${keyword[2].trim()}` };
    }
    return { href: `sms:${digits(text)}`, label: `Text ${text}` };
}

const safeHttp = (url) => (typeof url === 'string' && /^https?:\/\//i.test(url) ? url : null);

/** @param {{level?:string, title?:string, message?:string, resources?:any[]}} data */
export function safetyCard(data, uid) {
    const level = ['crisis', 'abuse', 'support'].includes(data.level) ? data.level : 'support';
    const titleId = `safety-title-${uid}`;
    const card = h('section', { class: `safety-card safety-${level}`, 'aria-labelledby': titleId, role: 'region' },
        h('div', { class: 'safety-head' },
            icon('lifebuoy'),
            h('h2', { class: 'safety-title', id: titleId, dir: 'auto', text: data.title || 'You do not have to go through this alone' })),
        data.message ? h('p', { class: 'safety-message', dir: 'auto', text: data.message }) : null);

    const list = h('ul', { class: 'safety-resources' });
    for (const resource of data.resources || []) {
        const actions = h('div', { class: 'resource-actions' });
        if (resource.phone) {
            actions.append(h('a', { class: 'resource-action primary', href: `tel:${digits(resource.phone)}` },
                icon('phone'), `Call ${resource.phone}`));
        }
        if (resource.sms) {
            const sms = smsLink(resource.sms);
            actions.append(h('a', { class: 'resource-action', href: sms.href }, icon('chat-text'), sms.label));
        }
        const chat = safeHttp(resource.chat_url);
        if (chat) {
            actions.append(h('a', { class: 'resource-action', href: chat, target: '_blank', rel: 'noopener noreferrer' },
                icon('chat'), 'Chat online', h('span', { class: 'sr-only', text: ' (opens in a new tab)' })));
        }
        const site = safeHttp(resource.url);
        if (site) {
            actions.append(h('a', { class: 'resource-action quiet', href: site, target: '_blank', rel: 'noopener noreferrer' },
                icon('globe-simple'), 'Website', h('span', { class: 'sr-only', text: ` for ${resource.name || 'this resource'} (opens in a new tab)` })));
        }
        list.append(h('li', { class: 'safety-resource' },
            h('div', { class: 'resource-head' },
                h('span', { class: 'resource-name', dir: 'auto', text: resource.name || '' }),
                resource.region ? h('span', { class: 'resource-region', text: resource.region }) : null),
            resource.description || resource.hours
                ? h('p', { class: 'resource-desc', dir: 'auto', text: [resource.description, resource.hours].filter(Boolean).join(' · ') })
                : null,
            actions));
    }
    if (list.childElementCount) card.append(list);
    return card;
}

/* ---------------- Assistant ---------------- */

let uidCounter = 0;

export class AssistantMessage {
    /**
     * @param {{ctx:MessageContext, id?:string|null, date?:Date}} options
     */
    constructor({ ctx, id = null, date = new Date() }) {
        this.uid = ++uidCounter;
        this.ctx = ctx;
        this.id = id;
        this.content = '';
        /** @type {Array<{n:number, offset:number}>} */
        this.citations = [];
        /** @type {Map<number, any>} */
        this.citationSources = new Map();
        this.metaSources = [];
        this.frame = null;
        this.finalized = false;

        this.el = h('article', { class: 'message assistant', 'aria-label': 'rebbe.dev reply' });
        if (id) this.el.dataset.messageId = id;
        this.avatar = h('div', { class: 'message-avatar', 'aria-hidden': 'true' },
            h('img', { src: '/static/assets/brand/braided-r.svg', alt: '', width: '22', height: '22' }));
        this.main = h('div', { class: 'message-main' });
        this.safetySlot = h('div', { class: 'safety-slot' });
        this.noticeSlot = h('div', { class: 'notice-slot' });
        this.body = h('div', { class: 'message-content', dir: 'auto' });
        this.errorSlot = h('div', { class: 'error-slot' });
        this.sourcesSlot = h('div', { class: 'sources-slot' });
        this.footer = h('div', { class: 'message-footer' });
        this.main.append(this.safetySlot, this.noticeSlot, this.body, this.errorSlot, this.sourcesSlot, this.footer);
        this.el.append(this.avatar, this.main);
        this.renderer = new StreamingMarkdown(this.body);
        this.date = date;
    }

    /* --- streaming --- */

    setStatus(label) {
        if (this.finalized) return;
        if (!this.thinking) {
            this.thinking = h('div', { class: 'thinking', role: 'status' },
                h('span', { class: 'thinking-dots', 'aria-hidden': 'true' }, h('span'), h('span'), h('span')),
                h('span', { class: 'thinking-label shimmer-text' }));
            this.main.insertBefore(this.thinking, this.body);
        }
        const text = label || 'Thinking…';
        const target = this.thinking.querySelector('.thinking-label');
        if (target.textContent !== text) target.textContent = text;
    }

    clearStatus() {
        if (this.thinking) { this.thinking.remove(); this.thinking = null; }
    }

    showSafety(data) {
        this.safety = data;
        this.safetySlot.replaceChildren(safetyCard(data, this.uid));
        this.el.classList.add('has-safety');
        this.ctx.onGrow();
    }

    appendToken(text) {
        if (!text) return;
        this.content += text;
        this.clearStatus();
        this.body.classList.add('streaming');
        this.schedule();
    }

    addCitation(n, source) {
        const num = Number(n);
        if (!Number.isFinite(num)) return;
        this.citations.push({ n: num, offset: this.content.length });
        if (source) this.citationSources.set(num, source);
        this.schedule();
    }

    setMetadata(meta) {
        this.metadata = meta || {};
        this.metaSources = Array.isArray(this.metadata.sources) ? this.metadata.sources : [];
    }

    schedule() {
        if (this.frame !== null) return;
        this.frame = requestAnimationFrame(() => {
            this.frame = null;
            this.flush();
        });
    }

    flush() {
        this.renderer.update(withCitationMarkers(this.content, this.citations));
        this.ctx.onGrow();
    }

    get hasText() { return this.content.trim().length > 0; }

    /* --- completion --- */

    /**
     * @param {{messageId?:string|null, saveFailed?:boolean, stopped?:boolean, retracted?:boolean, retractionReason?:string}} [options]
     */
    finalize(options = {}) {
        if (this.frame !== null) { cancelAnimationFrame(this.frame); this.frame = null; }
        this.finalized = true;
        this.clearStatus();
        this.body.classList.remove('streaming');
        this.flush();
        if (options.messageId) this.setId(options.messageId);
        this.stopped = !!options.stopped;
        this.renderSources();
        this.renderFooter({ saveFailed: !!options.saveFailed });
        if (options.retracted) this.showRetractionNotice(options.retractionReason);
    }

    setId(id) {
        this.id = id;
        if (id) this.el.dataset.messageId = id;
        if (this.toolbar && id) this.toolbar.dataset.messageId = id;
    }

    sourceItems() {
        return buildSourceItems(this.citationSources, this.metaSources);
    }

    renderSources() {
        const items = this.sourceItems();
        const footer = sourcesFooter(items, (index, trigger) => this.ctx.onOpenSources(items, index, trigger));
        this.sourcesSlot.replaceChildren(...(footer ? [footer] : []));
        // Inline markers open the same panel at their source.
        this.body.onclick = (event) => {
            const marker = event.target.closest('.cite-marker');
            if (marker) {
                const n = Number(marker.dataset.cite);
                const index = Math.max(0, items.findIndex((item) => item.n === n));
                this.ctx.onOpenSources(items, index, marker);
                return;
            }
            const copy = event.target.closest('[data-action="copy-code"]');
            if (copy) {
                const code = copy.parentElement.querySelector('code');
                this.ctx.onCopy(code ? code.textContent : '');
            }
        };
    }

    renderFooter({ saveFailed = false } = {}) {
        const bar = h('div', { class: 'message-actions', role: 'toolbar', 'aria-label': 'Reply actions' });
        if (this.id) bar.dataset.messageId = this.id;
        bar.dataset.content = this.content;
        if (this.hasText) {
            bar.append(
                actionButton('copy', 'Copy response', 'copy', { className: 'copy-btn' }),
                actionButton('speak', 'Listen to response', 'speaker', { className: 'speak-btn', attrs: { 'aria-haspopup': 'menu', 'aria-expanded': 'false' } }),
            );
            if (!saveFailed) {
                bar.append(
                    actionButton('thumbs_up', 'Mark as a good response', 'thumbs-up', { className: 'thumbs-up-btn', attrs: { 'aria-pressed': 'false' } }),
                    actionButton('thumbs_down', 'Mark as a poor response', 'thumbs-down', { className: 'thumbs-down-btn', attrs: { 'aria-pressed': 'false' } }),
                );
            }
        }
        bar.append(actionButton('regenerate', 'Regenerate response', 'arrow-clockwise', { className: 'regenerate-btn' }));
        bar.addEventListener('click', (event) => {
            const button = event.target.closest('[data-action]');
            if (!button) return;
            const action = button.dataset.action;
            if (action === 'copy') this.ctx.onCopy(this.content);
            else if (action === 'speak') this.ctx.onSpeak(button, this.plainText(), this.id);
            else if (action === 'regenerate') this.ctx.onRegenerate();
            else this.ctx.onFeedback(this.id, action, button, bar);
        });
        this.toolbar = bar;

        const meta = h('div', { class: 'message-meta' },
            h('time', { class: 'message-time', datetime: this.date.toISOString(), text: formatTime(this.date) }),
            this.stopped ? h('span', { class: 'message-flag', text: 'Stopped' }) : null);
        this.footer.replaceChildren(bar, meta);
    }

    plainText() {
        return this.body.innerText || this.content;
    }

    /* --- error / retraction --- */

    /**
     * @param {{title:string, body?:string, tone?:'error'|'warning'|'info', actions?:Array<{label:string, onClick:()=>void, primary?:boolean, icon?:string}>}} options
     */
    showError({ title, body, tone = 'error', actions = [] }) {
        this.clearStatus();
        this.body.classList.remove('streaming');
        const box = h('div', { class: `inline-error tone-${tone}`, role: tone === 'error' ? 'alert' : 'status' },
            icon(tone === 'info' ? 'info' : tone === 'warning' ? 'warning' : 'wifi-slash'),
            h('div', { class: 'inline-error-copy' },
                h('p', { class: 'inline-error-title', text: title }),
                body ? h('p', { class: 'inline-error-body', text: body }) : null));
        if (actions.length) {
            const row = h('div', { class: 'inline-error-actions' });
            for (const action of actions) {
                const button = h('button', { class: `btn btn-sm ${action.primary ? 'btn-primary' : 'btn-quiet'}`, type: 'button' },
                    action.icon ? icon(action.icon) : null, action.label);
                button.addEventListener('click', action.onClick);
                row.append(button);
            }
            box.querySelector('.inline-error-copy').append(row);
        }
        this.errorSlot.replaceChildren(box);
        this.el.classList.add('has-error');
        this.ctx.onGrow();
        return box;
    }

    clearError() {
        this.errorSlot.replaceChildren();
        this.el.classList.remove('has-error');
    }

    showRetractionNotice(reason) {
        this.noticeSlot.replaceChildren(h('div', { class: 'retraction-notice', role: 'note' },
            icon('warning'),
            h('div', null,
                h('p', { class: 'retraction-title', text: "We've withdrawn part of this answer" }),
                reason ? h('p', { class: 'retraction-reason', dir: 'auto', text: reason }) : null)));
        this.el.classList.add('retracted');
    }

    retract(replacement, reason) {
        this.content = replacement || '';
        this.citations = [];
        this.citationSources.clear();
        this.renderer.reset();
        if (this.content) this.body.append(renderMarkdown(this.content));
        this.showRetractionNotice(reason);
        if (this.toolbar) this.toolbar.dataset.content = this.content;
        this.renderSources();
    }

    remove() {
        if (this.frame !== null) cancelAnimationFrame(this.frame);
        this.el.remove();
    }
}

/**
 * Rebuild a stored assistant message from history.
 * @param {{id?:string, content:string, created_at?:string, metadata?:any}} msg
 * @param {MessageContext} ctx
 */
export function assistantFromHistory(msg, ctx) {
    const view = new AssistantMessage({ ctx, id: msg.id || null, date: msg.created_at ? new Date(msg.created_at) : new Date() });
    let meta = msg.metadata || {};
    if (typeof meta === 'string') {
        try { meta = JSON.parse(meta); } catch { meta = {}; }
    }
    if (meta.safety_resources) view.showSafety(meta.safety_resources);
    view.setMetadata(meta);
    view.content = msg.content || '';
    if (Array.isArray(meta.citations)) {
        view.citations = meta.citations
            .filter((c) => c && Number.isFinite(Number(c.n)))
            .map((c) => ({ n: Number(c.n), offset: Number(c.offset) }));
        for (const src of view.metaSources) {
            if (src && typeof src === 'object' && Number.isFinite(Number(src.n))) view.citationSources.set(Number(src.n), src);
        }
    }
    view.finalize({ messageId: msg.id, retracted: !!meta.retracted, retractionReason: meta.retraction_reason });
    return view;
}
