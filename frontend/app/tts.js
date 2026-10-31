/**
 * Read aloud. The browser's speechSynthesis voice is the free default; the
 * premium voice (POST /api/speak, streamed 24 kHz 16-bit mono PCM) is an
 * explicit choice that costs credits and can answer 402.
 */
import { h, icon } from './dom.js';
import { trackTTSEvent } from './analytics.js';
import { showToast } from './toast.js';
import { ttsCreditCost, openPurchaseSheet, loadCredits } from './payments.js';

const PCM_RATE = 24000;
const hasBrowserVoice = () => 'speechSynthesis' in window && typeof window.SpeechSynthesisUtterance === 'function';

/** @type {{button:HTMLElement, stop:()=>void}|null} */
let playing = null;
let menu = null;
let audioContext = null;

function setButton(button, mode) {
    button.classList.toggle('loading', mode === 'loading');
    button.classList.toggle('playing', mode === 'playing');
    const label = mode === 'idle' ? 'Listen to response' : 'Stop reading aloud';
    button.setAttribute('aria-label', label);
    button.title = label;
}

export function stopSpeaking() {
    if (playing) {
        const current = playing;
        playing = null;
        current.stop();
        setButton(current.button, 'idle');
    }
}

function closeMenu() {
    if (!menu) return;
    const { el, button } = menu;
    menu = null;
    el.remove();
    button.setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', onOutside, true);
}

function onOutside(event) {
    if (menu && !menu.el.contains(event.target) && event.target !== menu.button) closeMenu();
}

/* --- browser voice --- */

function hebrewVoice(text) {
    return /[֐-׿]/.test(text) && text.replace(/[^֐-׿]/g, '').length > text.length * 0.3;
}

function speakWithBrowser(button, text) {
    const synth = window.speechSynthesis;
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = hebrewVoice(text) ? 'he-IL' : (document.documentElement.lang || 'en-US');
    utterance.rate = 1;
    utterance.onend = () => { if (playing && playing.button === button) { playing = null; setButton(button, 'idle'); } };
    utterance.onerror = utterance.onend;
    playing = { button, stop: () => synth.cancel() };
    setButton(button, 'playing');
    synth.speak(utterance);
}

/* --- premium voice --- */

async function speakPremium(button, text, messageId) {
    if (!audioContext) {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        audioContext = new Ctx({ sampleRate: PCM_RATE });
    }
    if (audioContext.state === 'suspended') await audioContext.resume();

    const controller = new AbortController();
    const sources = [];
    let stopped = false;
    playing = {
        button,
        stop: () => {
            stopped = true;
            controller.abort();
            sources.forEach((s) => { try { s.stop(); } catch { /* finished */ } });
            trackTTSEvent('stop', messageId);
        },
    };
    setButton(button, 'loading');
    const started = Date.now();
    trackTTSEvent('start', messageId, text.length);

    try {
        const response = await fetch('/api/speak', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, message_id: messageId || undefined }),
            credentials: 'include',
            signal: controller.signal,
        });
        if (response.status === 402) {
            playing = null;
            setButton(button, 'idle');
            trackTTSEvent('error', messageId, text.length, null, 'no_credits');
            openPurchaseSheet({ reason: `The premium voice uses ${ttsCreditCost()} credits. Add credits, or use the free browser voice.` });
            return;
        }
        if (!response.ok) throw new Error(`Speech generation failed (${response.status})`);
        loadCredits();

        const reader = response.body.getReader();
        let next = audioContext.currentTime;
        let leftover = new Uint8Array(0);
        let last = null;
        let first = true;
        while (true) {
            const { done, value } = await reader.read();
            if (done || stopped) break;
            const combined = new Uint8Array(leftover.length + value.length);
            combined.set(leftover);
            combined.set(value, leftover.length);
            const usable = combined.length - (combined.length % 2);
            leftover = combined.slice(usable);
            if (!usable) continue;
            const view = new DataView(combined.buffer, 0, usable);
            const samples = new Float32Array(usable / 2);
            for (let i = 0; i < samples.length; i += 1) samples[i] = view.getInt16(i * 2, true) / 32768;
            const buffer = audioContext.createBuffer(1, samples.length, PCM_RATE);
            buffer.getChannelData(0).set(samples);
            const source = audioContext.createBufferSource();
            source.buffer = buffer;
            source.connect(audioContext.destination);
            const at = Math.max(next, audioContext.currentTime);
            source.start(at);
            next = at + buffer.duration;
            sources.push(source);
            last = source;
            if (first) { setButton(button, 'playing'); first = false; }
        }
        if (last && !stopped) {
            last.onended = () => {
                if (playing && playing.button === button) { playing = null; setButton(button, 'idle'); }
                trackTTSEvent('complete', messageId, text.length, Date.now() - started);
            };
        } else if (!stopped) {
            playing = null;
            setButton(button, 'idle');
        }
    } catch (error) {
        if (stopped) return;
        playing = null;
        setButton(button, 'idle');
        showToast('Could not generate speech', { tone: 'error' });
        trackTTSEvent('error', messageId, text.length, null, error.message || 'Unknown error');
    }
}

/**
 * Speak button handler: stop if this message is playing, otherwise offer
 * the free browser voice and the premium voice.
 */
export function onSpeak(button, text, messageId) {
    if (playing && playing.button === button) { stopSpeaking(); return; }
    if (menu && menu.button === button) { closeMenu(); return; }
    closeMenu();

    const cost = ttsCreditCost();
    const options = [];
    if (hasBrowserVoice()) {
        options.push(h('button', { class: 'dropdown-item', type: 'button', role: 'menuitem', dataset: { voice: 'browser' } },
            icon('speaker'), h('span', null, 'Read aloud', h('small', { text: 'Device voice · free' }))));
    }
    options.push(h('button', { class: 'dropdown-item', type: 'button', role: 'menuitem', dataset: { voice: 'premium' } },
        icon('speaker'), h('span', null, 'Premium voice', h('small', { text: `${cost} credits` }))));

    const el = h('div', { class: 'menu speak-menu', role: 'menu', 'aria-label': 'Read aloud' }, ...options);
    document.body.append(el);
    const rect = button.getBoundingClientRect();
    const top = rect.bottom + 6 + 120 > window.innerHeight ? rect.top - 6 - el.offsetHeight : rect.bottom + 6;
    el.style.top = `${Math.max(8, top)}px`;
    el.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - el.offsetWidth - 8))}px`;
    button.setAttribute('aria-expanded', 'true');
    menu = { el, button };
    setTimeout(() => document.addEventListener('click', onOutside, true));

    el.addEventListener('click', (event) => {
        const choice = event.target.closest('[data-voice]');
        if (!choice) return;
        closeMenu();
        stopSpeaking();
        if (choice.dataset.voice === 'browser') speakWithBrowser(button, text);
        else speakPremium(button, text, messageId);
    });
    el.addEventListener('keydown', (event) => {
        const items = Array.from(el.querySelectorAll('[role="menuitem"]'));
        const index = items.indexOf(document.activeElement);
        if (event.key === 'Escape') { event.stopPropagation(); closeMenu(); button.focus(); }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            items[(index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
        }
    });
    el.querySelector('[role="menuitem"]').focus();
}
