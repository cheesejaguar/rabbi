/**
 * Bootstrap: wire modules, check the session, load first-paint data, route
 * deep links (/c/:id), and register global shortcuts.
 */
import { $, showScreen, isMobile } from './dom.js';
import { state, subscribe } from './store.js';
import { trackSessionStart } from './analytics.js';
import { modalOpen } from './a11y.js';
import { showToast } from './toast.js';
import {
    checkAuth, checkGuestStatus, renderSignedOut, restorePendingDraft, listenForPopupAuth,
} from './auth.js';
import { initSidebar, loadConversations, closeDrawer } from './sidebar.js';
import { initPayments, loadCredits, renderBalance } from './payments.js';
import { initSettings, showSettings } from './settings.js';
import { initDvar, loadDvarTorah, refreshAfterSponsorship } from './dvar.js';
import { initSponsor } from './sponsor.js';
import { checkCalendarStatus } from './calendar.js';
import { initSourcesPanel, closeSourcesPanel, sourcesPanelOpen } from './chat/sources.js';
import {
    initChat, openConversation, startNewConversation, routeConversationId, composers,
} from './chat/chat.js';

async function loadGreeting() {
    const text = $('greetingText');
    try {
        await fetch('/api/greeting');
    } catch { /* greeting copy is static */ }
    text.textContent = 'Shalom, how can I help?';
    text.classList.remove('hidden');
    $('greetingSkeleton').classList.add('hidden');
}

/** Mobile keyboards shrink the visual viewport, not the layout viewport. */
function trackViewport() {
    const vv = window.visualViewport;
    if (!vv) return;
    const apply = () => {
        document.documentElement.style.setProperty('--app-height', `${Math.round(vv.height)}px`);
    };
    vv.addEventListener('resize', apply);
    apply();
}

function isTyping(target) {
    return target instanceof HTMLElement
        && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
}

function bindShortcuts() {
    const mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
    document.querySelectorAll('[data-shortcut-mod]').forEach((el) => { el.textContent = mac ? '⌘K' : 'Ctrl K'; });

    document.addEventListener('keydown', (event) => {
        if (modalOpen()) return;
        const mod = event.metaKey || event.ctrlKey;
        if (mod && !event.shiftKey && !event.altKey && event.key.toLowerCase() === 'k') {
            event.preventDefault();
            startNewConversation();
            return;
        }
        if (event.key === '/' && !mod && !event.altKey && !isTyping(event.target)) {
            event.preventDefault();
            const { welcome, composer } = composers();
            (document.body.dataset.screen === 'chatScreen' ? composer : welcome).focus();
            return;
        }
        if (event.key === 'Escape') {
            if (sourcesPanelOpen()) { closeSourcesPanel(); return; }
            if ($('sidebar').classList.contains('open')) { closeDrawer(); $('menuBtn').focus(); }
        }
    });
}

function handlePaymentRedirects() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('payment') === 'success') {
        window.history.replaceState({}, '', window.location.pathname);
        showToast('Payment successful! Credits have been added to your account.');
    }
    if (params.get('sponsorship') === 'success') {
        const intent = params.get('payment_intent');
        window.history.replaceState({}, '', window.location.pathname);
        if (intent) {
            fetch('/api/payments/verify-and-fulfill', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ payment_intent_id: intent }),
                credentials: 'include',
            }).catch(() => {}).finally(() => loadDvarTorah(true));
        }
        showToast("Thank you! Your d'var Torah dedication has been received.");
    }
}

function restoreDraft() {
    const { welcome, composer } = composers();
    return restorePendingDraft((text) => {
        const target = document.body.dataset.screen === 'chatScreen' ? composer : welcome;
        target.value = text;
        target.focus();
    });
}

async function init() {
    showScreen('welcomeScreen');
    renderSignedOut();
    initChat();
    initSidebar({
        onOpen: (id) => openConversation(id),
        onNew: () => startNewConversation(),
        onDeletedCurrent: () => startNewConversation(),
        onSettings: showSettings,
    });
    initPayments();
    initSettings();
    initDvar();
    initSponsor({ onSponsored: refreshAfterSponsorship });
    initSourcesPanel();
    bindShortcuts();
    trackViewport();
    subscribe((changed) => { if (changed.includes('credits')) renderBalance(); });
    window.addEventListener('popstate', () => {
        const id = routeConversationId();
        if (id) openConversation(id, { push: false });
        else startNewConversation({ push: false });
    });
    listenForPopupAuth(() => {
        restoreDraft();
        loadConversations();
        loadCredits();
    });

    trackSessionStart();
    const authenticated = await checkAuth();
    checkCalendarStatus();
    await Promise.all([loadGreeting(), loadDvarTorah()]);

    if (!authenticated) {
        await checkGuestStatus();
        return;
    }

    loadCredits();
    handlePaymentRedirects();
    const deepLink = routeConversationId();
    await loadConversations({ skeleton: true });
    if (deepLink) await openConversation(deepLink, { push: false });
    restoreDraft();
    if (!deepLink && !isMobile()) $('messageInput').focus({ preventScroll: true });
}

init();

// Debug handle for tests and support (read-only use).
window.__rebbe = { state };
