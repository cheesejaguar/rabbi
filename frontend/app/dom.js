/**
 * Tiny DOM helpers shared by every module. No framework: `h()` builds real
 * elements (text is always assigned through textContent, never innerHTML).
 */

export const $ = (id) => document.getElementById(id);

/**
 * @param {string} tag
 * @param {Record<string, any>|null} [attrs]
 * @param {...(Node|string|null|undefined|false)} children
 * @returns {HTMLElement}
 */
export function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    if (attrs) {
        for (const [key, value] of Object.entries(attrs)) {
            if (value === null || value === undefined || value === false) continue;
            if (key === 'class') el.className = value;
            else if (key === 'text') el.textContent = value;
            else if (key === 'dataset') Object.assign(el.dataset, value);
            else if (key.startsWith('on') && typeof value === 'function') {
                el.addEventListener(key.slice(2), value);
            } else if (value === true) el.setAttribute(key, '');
            else el.setAttribute(key, String(value));
        }
    }
    for (const child of children) {
        if (child === null || child === undefined || child === false) continue;
        el.append(child);
    }
    return el;
}

/** Decorative Phosphor glyph. */
export const icon = (name) => h('span', { class: `ph-icon ph-${name}`, 'aria-hidden': 'true' });

export function show(el, visible = true) {
    if (el) el.classList.toggle('hidden', !visible);
}

/** Only one screen in <main> is visible at a time. */
const SCREENS = ['welcomeScreen', 'chatScreen', 'settingsScreen', 'dvarTorahScreen'];
export function showScreen(id) {
    for (const screen of SCREENS) show($(screen), screen === id);
    document.body.dataset.screen = id;
}
export const currentScreen = () => document.body.dataset.screen || 'welcomeScreen';

/** localStorage that never throws (private mode, blocked storage, quota). */
export const storage = {
    get(key) {
        try { return window.localStorage.getItem(key); } catch { return null; }
    },
    set(key, value) {
        try { window.localStorage.setItem(key, value); } catch { /* best effort */ }
    },
    remove(key) {
        try { window.localStorage.removeItem(key); } catch { /* best effort */ }
    },
};

export const session = {
    get(key) {
        try { return window.sessionStorage.getItem(key); } catch { return null; }
    },
    set(key, value) {
        try { window.sessionStorage.setItem(key, value); } catch { /* best effort */ }
    },
    remove(key) {
        try { window.sessionStorage.removeItem(key); } catch { /* best effort */ }
    },
};

export const prefersReducedMotion = () =>
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export const isMobile = () => window.innerWidth <= 820;

export function formatTime(date) {
    return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

export function localDateString(date = new Date()) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Fade a short piece of chrome to its new text instead of an instant swap. */
export function updateTextWithFade(el, text) {
    if (!el || el.textContent === text) return;
    if (prefersReducedMotion()) { el.textContent = text; return; }
    el.classList.add('text-fade-out');
    setTimeout(() => {
        el.textContent = text;
        el.classList.remove('text-fade-out');
    }, 150);
}

export function newId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    return 'req_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
}
