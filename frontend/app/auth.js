/**
 * Authentication: session check, the sidebar identity, the sign-in popup
 * (postMessage 'rebbe-auth-complete'), the guest allowance, and the pending
 * draft that survives a login round-trip.
 */
import { $, h, icon, session, updateTextWithFade } from './dom.js';
import { state, set } from './store.js';
import { api } from './api.js';
import { showToast } from './toast.js';

const PENDING_DRAFT_KEY = 'pendingPromptDraft';

export async function checkAuth() {
    try {
        const response = await fetch('/auth/check', { credentials: 'include' });
        if (!response.ok) return false;
        const data = await response.json();
        if (data.authenticated && data.user) {
            set({ user: data.user });
            renderSignedIn();
            return true;
        }
        return false;
    } catch (error) {
        console.warn('Auth check failed:', error);
        return false;
    }
}

export async function checkGuestStatus() {
    try {
        const status = await api.get('/guest/status');
        set({ guestStatus: status });
        return status;
    } catch {
        return null;
    }
}

function initials(user) {
    const first = user.first_name || '';
    const last = user.last_name || '';
    if (first && last) return (first[0] + last[0]).toUpperCase();
    if (first) return first[0].toUpperCase();
    if (user.email) return user.email[0].toUpperCase();
    return '?';
}

export function fullName(user) {
    return [user.first_name, user.last_name].filter(Boolean).join(' ') || 'User';
}

function menuItem(tag, attrs, iconName, label) {
    return h(tag, { class: 'dropdown-item', role: 'menuitem', ...attrs }, icon(iconName), label);
}

export function renderSignedIn() {
    const user = state.user;
    if (!user) return;
    const avatar = $('sidebarUserAvatar');
    avatar.classList.remove('ph-icon', 'ph-arrow-right');
    avatar.style.fontSize = '';
    updateTextWithFade(avatar, initials(user));
    updateTextWithFade($('sidebarUserName'), fullName(user));
    $('sidebarUserContext').textContent = user.email || 'Account';

    const dropdown = $('sidebarDropdown');
    dropdown.replaceChildren(
        menuItem('button', { id: 'settingsBtn', type: 'button' }, 'gear', 'Settings'),
        menuItem('a', { href: '/privacy' }, 'shield', 'Privacy'),
        menuItem('a', { href: '/terms' }, 'book-open', 'Terms'),
        user.is_admin ? menuItem('a', { href: '/admin', id: 'adminLink' }, 'shield', 'Admin') : null,
        h('div', { class: 'dropdown-divider', role: 'separator' }),
        h('a', { href: '/auth/logout', class: 'dropdown-item dropdown-item-danger', role: 'menuitem' }, icon('sign-out'), 'Sign out'),
    );
    hideLoginPrompt();
}

export function renderSignedOut() {
    const avatar = $('sidebarUserAvatar');
    avatar.replaceChildren();
    avatar.classList.add('ph-icon', 'ph-arrow-right');
    avatar.style.fontSize = '1rem';
    $('sidebarUserName').textContent = 'Sign in';
    $('sidebarUserContext').textContent = 'Save your conversations';
    $('sidebarDropdown').replaceChildren(
        h('a', { href: '/auth/login', class: 'dropdown-item', role: 'menuitem' }, icon('arrow-right'), 'Sign in'),
        menuItem('a', { href: '/privacy' }, 'shield', 'Privacy'),
        menuItem('a', { href: '/terms' }, 'book-open', 'Terms'),
    );
}

/* --- pending draft across login --- */

export function savePendingDraft(message) {
    const trimmed = (message || '').trim();
    if (trimmed) session.set(PENDING_DRAFT_KEY, trimmed);
}
export const getPendingDraft = () => session.get(PENDING_DRAFT_KEY);
export const clearPendingDraft = () => session.remove(PENDING_DRAFT_KEY);

/** @param {(text:string)=>void} restore puts the text back into a composer */
export function restorePendingDraft(restore) {
    const draft = getPendingDraft();
    if (!draft) return false;
    clearPendingDraft();
    restore(draft);
    showToast('Your message is ready to send.');
    return true;
}

/* --- popup login --- */

export function openLoginPopup() {
    const width = 500;
    const height = 700;
    const left = window.screenX + (window.outerWidth - width) / 2;
    const top = window.screenY + (window.outerHeight - height) / 2;
    const popup = window.open('/auth/login?popup=1', 'rebbeAuth',
        `width=${width},height=${height},left=${left},top=${top},resizable=yes,scrollbars=yes`);
    if (!popup) {
        // Popup blocked: full redirect; the sessionStorage draft is restored on return.
        window.location.href = '/auth/login';
    }
}

/** @param {()=>void} onAuthenticated */
export function listenForPopupAuth(onAuthenticated) {
    window.addEventListener('message', async (event) => {
        if (event.origin !== window.location.origin) return;
        if (!event.data || event.data.type !== 'rebbe-auth-complete') return;
        if (await checkAuth()) {
            hideLoginPrompt();
            onAuthenticated();
        }
    });
}

export function showLoginPrompt(reason) {
    let prompt = $('loginPrompt');
    const message = reason
        || (getPendingDraft() ? 'Sign in to send your message' : 'Please sign in to chat with rebbe.dev');
    if (!prompt) {
        prompt = h('div', { id: 'loginPrompt', class: 'login-prompt', role: 'dialog', 'aria-labelledby': 'loginPromptText' });
        document.body.append(prompt);
    }
    const signIn = h('button', { class: 'btn btn-primary login-prompt-btn', id: 'loginPromptSignInBtn', type: 'button', text: 'Sign in' });
    const close = h('button', { class: 'icon-btn login-prompt-close', id: 'loginPromptCloseBtn', type: 'button', 'aria-label': 'Close sign-in prompt' }, icon('x'));
    signIn.addEventListener('click', openLoginPopup);
    close.addEventListener('click', hideLoginPrompt);
    prompt.replaceChildren(h('div', { class: 'login-prompt-content' },
        h('img', { src: '/static/assets/brand/braided-r.svg', alt: '', width: '28', height: '28' }),
        h('p', { id: 'loginPromptText', text: message }),
        signIn, close));
    prompt.classList.add('visible');
    requestAnimationFrame(() => signIn.focus());
}

export function hideLoginPrompt() {
    const prompt = $('loginPrompt');
    if (prompt) prompt.classList.remove('visible');
}
