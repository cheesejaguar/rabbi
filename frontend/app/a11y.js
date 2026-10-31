/**
 * Screen-reader announcements and modal focus management.
 *
 * Two live regions keep status chatter (#appLiveRegion) from clobbering the
 * finished-reply announcement (#messageLiveRegion). The thread itself is not
 * a live region, so streamed tokens are never read out one by one.
 */
import { $ } from './dom.js';

function speakInto(region, message) {
    if (!region) return;
    region.textContent = '';
    requestAnimationFrame(() => { region.textContent = message; });
}

export function announce(message) {
    speakInto($('appLiveRegion'), message);
}

/** Announce a completed assistant reply (plain text, trimmed for sanity). */
export function announceMessage(text) {
    const plain = String(text || '').replace(/\s+/g, ' ').trim();
    const clipped = plain.length > 1200 ? plain.slice(0, 1200) + '…' : plain;
    speakInto($('messageLiveRegion'), `rebbe.dev replied: ${clipped}`);
}

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

export function focusables(root) {
    return Array.from(root.querySelectorAll(FOCUSABLE)).filter((el) => el.offsetParent !== null);
}

/** @type {Array<{el:HTMLElement, onClose:()=>void, returnFocus:HTMLElement|null}>} */
const stack = [];

function onKeydown(event) {
    const top = stack[stack.length - 1];
    if (!top) return;
    if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        top.onClose();
        return;
    }
    if (event.key !== 'Tab') return;
    const items = focusables(top.el);
    if (!items.length) {
        event.preventDefault();
        top.el.focus();
        return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && (document.activeElement === first || !top.el.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !top.el.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
    }
}

/**
 * Show a dialog, trap focus inside it, and close on Escape/backdrop.
 * @param {HTMLElement} el overlay element with role=dialog
 * @param {{onClose:()=>void, initialFocus?:HTMLElement}} options
 */
export function openModal(el, { onClose, initialFocus } = {}) {
    if (stack.some((entry) => entry.el === el)) return;
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    stack.push({ el, onClose, returnFocus });
    el.classList.remove('hidden');
    el.classList.add('visible');
    el.setAttribute('aria-hidden', 'false');
    document.body.classList.add('has-modal');
    if (stack.length === 1) document.addEventListener('keydown', onKeydown, true);
    requestAnimationFrame(() => {
        const target = initialFocus || focusables(el)[0] || el;
        target.focus();
    });
}

export function closeModal(el) {
    const index = stack.findIndex((entry) => entry.el === el);
    el.classList.remove('visible');
    el.classList.add('hidden');
    el.setAttribute('aria-hidden', 'true');
    if (index === -1) return;
    const [entry] = stack.splice(index, 1);
    if (!stack.length) {
        document.removeEventListener('keydown', onKeydown, true);
        document.body.classList.remove('has-modal');
    }
    if (entry.returnFocus && document.contains(entry.returnFocus)) entry.returnFocus.focus();
}

export const modalOpen = () => stack.length > 0;

/** Close when the backdrop itself (not the sheet) is clicked. */
export function closeOnBackdrop(el, close) {
    el.addEventListener('click', (event) => {
        if (event.target === el) close();
    });
}
