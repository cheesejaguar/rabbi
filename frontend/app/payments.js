/**
 * Credits: balance (settings value + composer pill with a low-balance hint)
 * and the Stripe purchase sheet. Packages come from GET /api/payments/packages
 * with the recommended pack preselected.
 *
 * Fulfillment is dual-path: Stripe webhooks in production, and the
 * non-production /payments/verify-and-fulfill shortcut (404 in production).
 */
import { $, h, updateTextWithFade } from './dom.js';
import { state, set } from './store.js';
import { api } from './api.js';
import { openModal, closeModal, closeOnBackdrop, announce } from './a11y.js';
import { showToast } from './toast.js';

const LOW_BALANCE = 3;
const FALLBACK_PACKAGES = [
    { id: 'credits_55', credits: 55, display_price: '$2.00', label: 'Starter' },
    { id: 'credits_160', credits: 160, display_price: '$5.00', label: 'Standard', recommended: true },
    { id: 'credits_400', credits: 400, display_price: '$12.00', label: 'Plus' },
];

let stripe = null;
let elements = null;
let paymentElement = null;
let packages = null;
let selectedPackage = null;
/** @type {(()=>void)|null} */
let onPurchased = null;

/* ---------------- Balance ---------------- */

export async function loadCredits() {
    const value = $('creditsValue');
    try {
        const data = await api.get('/credits');
        set({ credits: data });
    } catch (error) {
        console.warn('Failed to load credits:', error);
        value.classList.remove('skeleton', 'settings-value-skeleton');
        updateTextWithFade(value, 'Error loading');
    }
}

/** Apply a server-reported balance (e.g. done.credits_remaining). */
export function setBalance(credits) {
    if (!Number.isFinite(Number(credits))) return;
    set({ credits: { ...(state.credits || {}), credits: Number(credits), unlimited: false } });
}

export const ttsCreditCost = () => {
    const cost = state.credits && Number(state.credits.tts_credit_cost);
    return Number.isFinite(cost) && cost > 0 ? cost : 8;
};

export function renderBalance() {
    const data = state.credits;
    const value = $('creditsValue');
    const pill = $('creditsPill');
    const hint = $('creditsHint');
    if (!data) return;
    value.classList.remove('skeleton', 'settings-value-skeleton');
    if (data.unlimited) {
        updateTextWithFade(value, 'Unlimited');
        value.classList.remove('credits-value');
        pill.classList.add('hidden');
        hint.classList.add('hidden');
        return;
    }
    const credits = Number(data.credits) || 0;
    updateTextWithFade(value, String(credits));
    value.classList.add('credits-value');

    const low = credits <= LOW_BALANCE;
    pill.classList.remove('hidden');
    pill.classList.toggle('low', low);
    $('creditsPillValue').textContent = `${credits} ${credits === 1 ? 'credit' : 'credits'}`;
    pill.setAttribute('aria-label', `${credits} ${credits === 1 ? 'credit' : 'credits'} left. Add credits.`);
    // Never nudge toward a purchase while someone may be in crisis.
    const showHint = low && !state.crisisTurn;
    hint.classList.toggle('hidden', !showHint);
    hint.textContent = credits === 0 ? 'Out of credits' : 'Running low';
}

/* ---------------- Packages ---------------- */

function normalizePackages(data) {
    const raw = data && data.packages;
    let list = [];
    if (Array.isArray(raw)) list = raw.map((p) => ({ ...p, id: p.id || p.package_id }));
    else if (raw && typeof raw === 'object') list = Object.entries(raw).map(([id, p]) => ({ id, ...p }));
    return list.filter((p) => p.id && Number(p.credits) > 0);
}

async function ensurePackages() {
    if (packages) return packages;
    try {
        const list = normalizePackages(await api.get('/payments/packages'));
        packages = list.length ? list : FALLBACK_PACKAGES;
    } catch {
        packages = FALLBACK_PACKAGES;
    }
    return packages;
}

function renderPackages() {
    const fieldset = $('packageSelection');
    const legend = fieldset.querySelector('legend');
    const cards = packages.map((pkg) => {
        const selected = pkg.id === selectedPackage;
        const card = h('button', {
            class: 'package-card credit-package-card' + (selected ? ' selected' : '') + (pkg.recommended ? ' recommended' : ''),
            type: 'button',
            'aria-pressed': String(selected),
            dataset: { package: pkg.id },
        },
        pkg.recommended ? h('span', { class: 'package-badge', text: 'Most chosen' }) : null,
        pkg.label ? h('span', { class: 'package-label', text: pkg.label }) : null,
        h('span', { class: 'package-credits', text: `${pkg.credits} credits` }),
        h('span', { class: 'package-price numeric', text: pkg.display_price || '' }),
        pkg.per_message ? h('span', { class: 'package-per numeric', text: `${pkg.per_message} per message` }) : null);
        card.addEventListener('click', () => selectPackage(pkg.id));
        return card;
    });
    fieldset.replaceChildren(legend, ...cards);
}

function selectPackage(id) {
    if (id === selectedPackage) return;
    selectedPackage = id;
    $('packageSelection').querySelectorAll('.package-card').forEach((card) => {
        const selected = card.dataset.package === id;
        card.classList.toggle('selected', selected);
        card.setAttribute('aria-pressed', String(selected));
    });
    initializePaymentForm();
}

/* ---------------- Stripe ---------------- */

export function stripeAppearance() {
    const dark = document.documentElement.dataset.theme === 'dark';
    return {
        theme: dark ? 'night' : 'stripe',
        variables: {
            colorPrimary: dark ? '#86a8e3' : '#315da8',
            colorBackground: dark ? '#161f2c' : '#fafcfe',
            colorText: dark ? '#eff4fa' : '#122033',
            colorDanger: dark ? '#f08b8b' : '#b23a3a',
            fontFamily: 'Hanken Grotesk, Arial, sans-serif',
            borderRadius: '8px',
            spacingUnit: '4px',
        },
    };
}

export function loadStripeJs() {
    return new Promise((resolve, reject) => {
        if (window.Stripe) { resolve(); return; }
        const script = document.createElement('script');
        script.src = 'https://js.stripe.com/v3/';
        script.onload = resolve;
        script.onerror = () => reject(new Error('Failed to load Stripe.js'));
        document.head.appendChild(script);
    });
}

export function getStripe(publishableKey) {
    if (!stripe) stripe = window.Stripe(publishableKey);
    return stripe;
}

/** Elements groups that should follow theme changes (purchase + sponsor). */
export const themedElements = new Set();

window.addEventListener('rebbe-theme-change', () => {
    const appearance = stripeAppearance();
    themedElements.forEach((instance) => {
        try { instance.update({ appearance }); } catch { /* stale group */ }
    });
});

export function renderPaymentLoadError(container, message) {
    container.replaceChildren(h('p', { class: 'payment-error-text', role: 'alert', text: message || 'Failed to load payment form. Please try again.' }));
}

function setPurchaseButton(text, spinner = false) {
    const button = $('submitPayment');
    button.querySelector('.btn-text').textContent = text;
    button.querySelector('.purchase-spinner').classList.toggle('hidden', !spinner);
}

let formToken = 0;

async function initializePaymentForm() {
    const container = $('paymentElementContainer');
    const submit = $('submitPayment');
    const token = ++formToken;
    submit.disabled = true;
    container.replaceChildren(h('div', { class: 'payment-loading', text: 'Loading payment form...' }));
    try {
        const intent = await api.post('/payments/create-intent', { package_id: selectedPackage });
        if (token !== formToken) return;
        if (!window.Stripe) await loadStripeJs();
        const instance = getStripe(intent.publishable_key);
        if (elements) themedElements.delete(elements);
        elements = instance.elements({
            clientSecret: intent.client_secret,
            customerSessionClientSecret: intent.customer_session_client_secret,
            appearance: stripeAppearance(),
        });
        themedElements.add(elements);
        paymentElement = elements.create('payment', { layout: 'tabs' });
        container.replaceChildren();
        paymentElement.mount(container);
        paymentElement.on('ready', () => { submit.disabled = false; });
        paymentElement.on('change', (event) => { submit.disabled = !event.complete; });
    } catch (error) {
        if (token !== formToken) return;
        console.warn('Failed to initialize payment form:', error);
        renderPaymentLoadError(container, error.message);
    }
}

function resetSheet() {
    $('packageSelection').classList.remove('hidden');
    $('modalFooter').classList.remove('hidden');
    $('paymentElementContainer').classList.remove('hidden');
    $('paymentStatus').classList.add('hidden');
    $('paymentSuccess').classList.add('hidden');
    $('paymentError').classList.add('hidden');
    $('submitPayment').disabled = true;
    setPurchaseButton('Pay now');
}

/**
 * Open the purchase sheet.
 * @param {{reason?: string, onPurchased?: ()=>void}} [options]
 */
export async function openPurchaseSheet(options = {}) {
    onPurchased = options.onPurchased || null;
    const reasonEl = $('purchaseModalReason');
    reasonEl.textContent = options.reason || 'One credit per message. Credits never expire.';
    reasonEl.classList.toggle('reason-alert', !!options.reason);
    resetSheet();
    openModal($('purchaseModal'), { onClose: closePurchaseSheet });
    await ensurePackages();
    const recommended = packages.find((p) => p.recommended) || packages[0];
    selectedPackage = recommended.id;
    renderPackages();
    await initializePaymentForm();
}

export function closePurchaseSheet() {
    closeModal($('purchaseModal'));
    formToken += 1;
    if (paymentElement) { try { paymentElement.destroy(); } catch { /* already gone */ } paymentElement = null; }
    if (elements) themedElements.delete(elements);
    elements = null;
}

function showSuccess() {
    $('packageSelection').classList.add('hidden');
    $('paymentElementContainer').classList.add('hidden');
    $('modalFooter').classList.add('hidden');
    $('paymentStatus').classList.remove('hidden');
    $('paymentSuccess').classList.remove('hidden');
    announce('Payment successful. Credits were added.');
}

function showError(message) {
    $('paymentErrorMessage').textContent = message;
    $('paymentStatus').classList.remove('hidden');
    $('paymentError').classList.remove('hidden');
    setTimeout(() => $('paymentError').classList.add('hidden'), 6000);
}

async function finishPurchase(note) {
    showSuccess();
    if (note) showToast(note);
    // Optimistic grant; the webhook confirms server-side.
    const pkg = packages && packages.find((p) => p.id === selectedPackage);
    if (pkg && state.credits && !state.credits.unlimited) {
        setBalance((Number(state.credits.credits) || 0) + Number(pkg.credits));
    }
    loadCredits();
    const done = onPurchased;
    onPurchased = null;
    setTimeout(() => {
        closePurchaseSheet();
        if (done) done();
    }, 1600);
}

async function handleSubmit() {
    const submit = $('submitPayment');
    if (!stripe || !elements) return;
    submit.disabled = true;
    setPurchaseButton('Processing...', true);
    try {
        const { error, paymentIntent } = await stripe.confirmPayment({
            elements,
            confirmParams: { return_url: window.location.origin + '/?payment=success' },
            redirect: 'if_required',
        });
        if (error) {
            showError(error.message);
            submit.disabled = false;
            setPurchaseButton('Pay now');
            return;
        }
        if (paymentIntent && paymentIntent.status === 'succeeded') {
            setPurchaseButton('Adding credits...', true);
            try {
                const response = await fetch('/api/payments/verify-and-fulfill', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ payment_intent_id: paymentIntent.id }),
                    credentials: 'include',
                });
                if (response.status === 404) await finishPurchase();
                else {
                    const result = await response.json().catch(() => ({}));
                    await finishPurchase(result.success ? null : 'Payment received. Credits will be added shortly.');
                }
            } catch {
                await finishPurchase('Payment received. Credits will be added shortly.');
            }
        } else {
            await finishPurchase();
        }
    } catch (error) {
        console.warn('Payment error:', error);
        showError('An unexpected error occurred.');
        submit.disabled = false;
        setPurchaseButton('Pay now');
    }
}

export function initPayments() {
    $('buyCreditsBtn').addEventListener('click', () => openPurchaseSheet());
    $('creditsPill').addEventListener('click', () => openPurchaseSheet());
    $('closePurchaseModal').addEventListener('click', closePurchaseSheet);
    closeOnBackdrop($('purchaseModal'), closePurchaseSheet);
    $('submitPayment').addEventListener('click', handleSubmit);
}
