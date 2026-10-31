/**
 * Weekly d'var Torah: welcome-screen preview, full reading screen with
 * sponsor dedications, and the sponsor call to action.
 */
import { $, h, localDateString, showScreen } from './dom.js';
import { state } from './store.js';
import { openSponsorModal } from './sponsor.js';
import { showLoginPrompt } from './auth.js';
import { blockDirection } from './chat/markdown.js';

let data = null;
let returnScreen = 'welcomeScreen';

const PREFIXES = {
    memory: 'In loving memory of',
    honor: 'In honor of',
    refuah: 'For a refuah shleima for',
    gratitude: 'In gratitude for',
    general: 'Dedicated by',
};

export const formatDedication = (s) => `${PREFIXES[s.dedication_type] || 'Dedicated:'} ${s.dedication}`;

export async function loadDvarTorah(fresh = false) {
    try {
        const url = `/api/dvar-torah?client_date=${encodeURIComponent(localDateString())}`;
        const response = await fetch(url, fresh ? { cache: 'no-store' } : undefined);
        if (!response.ok) return;
        const next = await response.json();
        if (next.is_holiday_week || !next.content) return;
        data = next;
        $('dvarTorahParsha').textContent = `${data.parsha_name} / ${data.parsha_name_hebrew}`;
        const preview = data.content.replace(/\s+/g, ' ').trim();
        $('dvarTorahPreview').textContent = preview.length > 200 ? preview.slice(0, 200).replace(/\s+\S*$/, '') + '…' : preview;
        $('dvarTorahPreview').dir = blockDirection(preview);
        $('dvarTorahSection').classList.remove('hidden');
    } catch (error) {
        console.warn("Failed to load d'var Torah:", error);
    } finally {
        $('dvarTorahSkeleton').classList.add('hidden');
    }
}

export function showDvarTorah() {
    if (!data) return;
    const visible = document.body.dataset.screen;
    if (visible && visible !== 'dvarTorahScreen') returnScreen = visible;
    showScreen('dvarTorahScreen');
    $('dvarTorahScreenTitle').textContent = `Parashat ${data.parsha_name}`;

    const parts = [];
    if (data.sponsors && data.sponsors.length) {
        parts.push(h('div', { class: 'dvar-sponsors' },
            ...data.sponsors.map((s) => h('p', { class: 'dvar-sponsor-line', dir: 'auto', text: formatDedication(s) }))));
    }
    parts.push(h('div', { class: 'dvar-torah-body' },
        ...data.content.split('\n\n').filter((p) => p.trim())
            .map((p) => h('p', { dir: blockDirection(p), text: p.replace(/\n/g, ' ') }))));
    const sponsor = h('button', { class: 'btn btn-quiet sponsor-btn', id: 'sponsorDvarBtn', type: 'button', text: "Sponsor this week's d'var Torah" });
    sponsor.addEventListener('click', () => {
        if (!state.user) { showLoginPrompt(); return; }
        openSponsorModal();
    });
    parts.push(h('div', { class: 'dvar-sponsor-cta' }, sponsor,
        h('p', { class: 'sponsor-hint', text: "Dedicate this week's Torah learning in memory or in honor of a loved one." })));
    $('dvarTorahScreenContent').replaceChildren(...parts);
    $('dvarTorahScreen').scrollTop = 0;
}

export function hideDvarTorah() {
    showScreen(returnScreen === 'chatScreen' && !$('chatMessages').childElementCount ? 'welcomeScreen' : returnScreen);
}

/** Refresh data after a sponsorship and re-render if the reader is on it. */
export async function refreshAfterSponsorship() {
    await loadDvarTorah(true);
    if (document.body.dataset.screen === 'dvarTorahScreen') showDvarTorah();
}

export function initDvar() {
    $('dvarTorahExpandBtn').addEventListener('click', showDvarTorah);
    $('dvarTorahBackBtn').addEventListener('click', hideDvarTorah);
}
