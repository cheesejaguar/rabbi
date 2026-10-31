/**
 * D'var Torah sponsorship (tzedakah): pick a chai-multiple tier, write a
 * dedication, then pay through a Stripe Payment Element.
 */
import { $, h, localDateString } from './dom.js';
import { api } from './api.js';
import { openModal, closeModal, closeOnBackdrop, announce } from './a11y.js';
import { getStripe, loadStripeJs, renderPaymentLoadError, stripeAppearance, themedElements } from './payments.js';

let tier = 'chai';
let elements = null;
let paymentElement = null;
let stripe = null;
/** @type {()=>Promise<void>} */
let onSponsored = async () => {};

function selectTier(next) {
    tier = next;
    $('sponsorModal').querySelectorAll('.package-card[data-tier]').forEach((card) => {
        const selected = card.dataset.tier === tier;
        card.classList.toggle('selected', selected);
        card.setAttribute('aria-pressed', String(selected));
    });
}

function reset() {
    $('sponsorStepDetails').classList.remove('hidden');
    $('sponsorStepPayment').classList.add('hidden');
    $('sponsorStatus').classList.add('hidden');
    $('sponsorSuccess').classList.add('hidden');
    $('sponsorError').classList.add('hidden');
    $('sponsorDetailsError').classList.add('hidden');
    $('submitSponsorship').disabled = true;
    selectTier('chai');
}

export function openSponsorModal() {
    reset();
    openModal($('sponsorModal'), { onClose: closeSponsorModal });
}

export function closeSponsorModal() {
    closeModal($('sponsorModal'));
    if (paymentElement) { try { paymentElement.destroy(); } catch { /* gone */ } paymentElement = null; }
    if (elements) themedElements.delete(elements);
    elements = null;
}

function showSponsorError(message) {
    $('sponsorErrorMessage').textContent = message;
    $('sponsorError').classList.remove('hidden');
    setTimeout(() => $('sponsorError').classList.add('hidden'), 6000);
}

async function startPayment() {
    const dedication = $('sponsorDedication').value.trim();
    const dedicationType = $('sponsorDedicationType').value;
    const errorEl = $('sponsorDetailsError');
    if (dedication.length < 2) {
        errorEl.textContent = 'Please enter a dedication (e.g. a name).';
        errorEl.classList.remove('hidden');
        $('sponsorDedication').focus();
        return;
    }
    errorEl.classList.add('hidden');
    const container = $('sponsorPaymentElementContainer');
    $('sponsorStepDetails').classList.add('hidden');
    $('sponsorStepPayment').classList.remove('hidden');
    container.replaceChildren(h('div', { class: 'payment-loading', text: 'Loading payment form...' }));
    try {
        const intent = await api.post('/payments/create-sponsorship-intent', {
            tier_id: tier,
            dedication,
            dedication_type: dedicationType,
            client_date: localDateString(),
        });
        if (!window.Stripe) await loadStripeJs();
        stripe = getStripe(intent.publishable_key);
        elements = stripe.elements({
            clientSecret: intent.client_secret,
            customerSessionClientSecret: intent.customer_session_client_secret,
            appearance: stripeAppearance(),
        });
        themedElements.add(elements);
        paymentElement = elements.create('payment', { layout: 'tabs' });
        container.replaceChildren();
        paymentElement.mount(container);
        const submit = $('submitSponsorship');
        paymentElement.on('ready', () => { submit.disabled = false; });
        paymentElement.on('change', (event) => { submit.disabled = !event.complete; });
    } catch (error) {
        console.warn('Failed to start sponsorship payment:', error);
        renderPaymentLoadError(container, error.message);
    }
}

async function submit() {
    if (!stripe || !elements) return;
    const button = $('submitSponsorship');
    button.disabled = true;
    try {
        const { error, paymentIntent } = await stripe.confirmPayment({
            elements,
            confirmParams: { return_url: window.location.origin + '/?sponsorship=success' },
            redirect: 'if_required',
        });
        if (error) { showSponsorError(error.message); button.disabled = false; return; }
        if (paymentIntent && paymentIntent.status === 'succeeded') {
            try {
                await fetch('/api/payments/verify-and-fulfill', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ payment_intent_id: paymentIntent.id }),
                    credentials: 'include',
                });
            } catch { /* webhook completes it */ }
        }
        $('sponsorStepPayment').classList.add('hidden');
        $('sponsorStatus').classList.remove('hidden');
        $('sponsorSuccess').classList.remove('hidden');
        announce('Sponsorship completed successfully.');
        setTimeout(async () => {
            closeSponsorModal();
            await onSponsored();
        }, 2500);
    } catch (error) {
        console.warn('Sponsorship payment error:', error);
        showSponsorError('An unexpected error occurred.');
        button.disabled = false;
    }
}

/** @param {{onSponsored: ()=>Promise<void>}} options */
export function initSponsor(options) {
    onSponsored = options.onSponsored;
    const modal = $('sponsorModal');
    $('closeSponsorModal').addEventListener('click', closeSponsorModal);
    closeOnBackdrop(modal, closeSponsorModal);
    modal.querySelectorAll('.package-card[data-tier]').forEach((card) => {
        card.addEventListener('click', () => selectTier(card.dataset.tier));
    });
    $('sponsorContinueBtn').addEventListener('click', startPayment);
    $('submitSponsorship').addEventListener('click', submit);
}
