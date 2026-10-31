/**
 * Toasts: one at a time, optionally with an action (e.g. Undo).
 */
import { $, h } from './dom.js';

let current = null;

/**
 * @param {string} message
 * @param {{action?: {label:string, onClick:()=>void}, duration?: number, tone?: 'error'|'success'}} [options]
 */
export function showToast(message, options = {}) {
    const region = $('toastRegion') || document.body;
    if (current) {
        clearTimeout(current.timer);
        current.el.remove();
        current = null;
    }

    const toast = h('div', { class: 'toast' + (options.tone ? ` toast-${options.tone}` : ''), role: 'status' },
        h('span', { class: 'toast-text', text: message }));

    let dismissed = false;
    const dismiss = () => {
        if (dismissed) return;
        dismissed = true;
        toast.classList.remove('visible');
        setTimeout(() => toast.remove(), 250);
        if (current && current.el === toast) current = null;
    };

    if (options.action) {
        const button = h('button', { class: 'toast-action', type: 'button', text: options.action.label });
        button.addEventListener('click', () => {
            options.action.onClick();
            dismiss();
        });
        toast.append(button);
    }

    region.append(toast);
    requestAnimationFrame(() => toast.classList.add('visible'));
    const timer = setTimeout(dismiss, options.duration || (options.action ? 5000 : 2400));
    current = { el: toast, timer };
    return dismiss;
}
