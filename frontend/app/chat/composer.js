/**
 * Composer: textarea + send/stop, keyboard shortcuts, auto-resize, paste
 * cleanup, a character counter near the limit, and per-conversation drafts.
 */
import { storage } from '../dom.js';

export const MAX_CHARS = 4000;
const COUNTER_FROM = 3500;
const DRAFT_PREFIX = 'rebbe-draft:';
// Zero-width and bidi-control characters that sneak in from copy/paste.
const INVISIBLE = /[​-‍⁠﻿‪-‮⁦-⁩]|[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g;

const coarsePointer = () => window.matchMedia('(pointer: coarse)').matches;

export class Composer {
    /**
     * @param {{
     *   textarea: HTMLTextAreaElement,
     *   sendBtn: HTMLButtonElement,
     *   stopBtn?: HTMLButtonElement|null,
     *   maxHeight?: number,
     *   onSubmit: (text:string)=>void,
     *   onStop?: ()=>void,
     * }} options
     */
    constructor({ textarea, sendBtn, stopBtn = null, maxHeight = 220, onSubmit, onStop }) {
        this.textarea = textarea;
        this.sendBtn = sendBtn;
        this.stopBtn = stopBtn;
        this.maxHeight = maxHeight;
        this.onSubmit = onSubmit;
        this.counter = textarea.closest('.composer').querySelector('[data-char-counter]');
        this.busy = false;
        this.draftKey = null;
        this.draftTimer = null;

        textarea.addEventListener('input', () => {
            this.refresh();
            this.scheduleDraftSave();
        });
        textarea.addEventListener('keydown', (event) => {
            if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return;
            if (coarsePointer()) return; // Phones: Enter inserts a newline; tap send.
            event.preventDefault();
            this.submit();
        });
        textarea.addEventListener('paste', (event) => {
            const text = event.clipboardData && event.clipboardData.getData('text/plain');
            if (!text) return;
            const cleaned = text.replace(/\r\n?/g, '\n').replace(INVISIBLE, '');
            if (cleaned === text) return;
            event.preventDefault();
            textarea.setRangeText(cleaned, textarea.selectionStart, textarea.selectionEnd, 'end');
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
        });
        sendBtn.addEventListener('click', () => this.submit());
        if (stopBtn && onStop) stopBtn.addEventListener('click', onStop);
    }

    get value() { return this.textarea.value; }

    set value(text) {
        this.textarea.value = text || '';
        this.refresh();
    }

    submit() {
        const text = this.textarea.value.trim();
        if (!text || this.busy || text.length > MAX_CHARS) return;
        this.onSubmit(text);
    }

    refresh() {
        const length = this.textarea.value.length;
        const hasContent = this.textarea.value.trim().length > 0;
        this.sendBtn.disabled = !hasContent || this.busy || length > MAX_CHARS;
        this.textarea.style.height = 'auto';
        this.textarea.style.height = Math.min(this.textarea.scrollHeight, this.maxHeight) + 'px';
        if (this.counter) {
            const near = length >= COUNTER_FROM;
            this.counter.classList.toggle('hidden', !near);
            this.counter.classList.toggle('over', length >= MAX_CHARS);
            if (near) this.counter.textContent = `${length.toLocaleString()} / ${MAX_CHARS.toLocaleString()}`;
        }
    }

    /** Streaming: hide send, show stop (chat composer only). */
    setBusy(busy) {
        this.busy = busy;
        this.sendBtn.classList.toggle('hidden', busy && !!this.stopBtn);
        this.sendBtn.classList.toggle('loading', busy && !this.stopBtn);
        if (this.stopBtn) this.stopBtn.classList.toggle('hidden', !busy);
        this.refresh();
    }

    focus() {
        this.textarea.focus();
        const end = this.textarea.value.length;
        this.textarea.setSelectionRange(end, end);
    }

    clear() {
        this.value = '';
        this.clearDraft();
    }

    /* --- drafts --- */

    useDraftKey(key) {
        this.flushDraft();
        this.draftKey = key;
        const saved = storage.get(DRAFT_PREFIX + key);
        this.value = saved || '';
    }

    scheduleDraftSave() {
        clearTimeout(this.draftTimer);
        this.draftTimer = setTimeout(() => this.flushDraft(), 250);
    }

    flushDraft() {
        clearTimeout(this.draftTimer);
        if (!this.draftKey) return;
        const text = this.textarea.value;
        if (text.trim()) storage.set(DRAFT_PREFIX + this.draftKey, text);
        else storage.remove(DRAFT_PREFIX + this.draftKey);
    }

    clearDraft() {
        clearTimeout(this.draftTimer);
        if (this.draftKey) storage.remove(DRAFT_PREFIX + this.draftKey);
    }
}

export function moveDraft(fromKey, toKey) {
    const text = storage.get(DRAFT_PREFIX + fromKey);
    if (text) storage.set(DRAFT_PREFIX + toKey, text);
    storage.remove(DRAFT_PREFIX + fromKey);
}
