/**
 * Weekly d'var Torah: welcome-screen preview, full reading screen with
 * sponsor dedications, and the sponsor call to action.
 */
import { $, h, icon, localDateString, showScreen } from './dom.js';
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
    if (data.audio_available) parts.push(listenControl());
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

/* ---------------- Read-aloud recording ---------------- */

// The recording is generated once on the server and cached; within a page
// session the downloaded file is reused, so replays cost nothing.
let audioUrl = null;
let audioFor = null;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function fetchRecording(status) {
    const url = `/api/dvar-torah/audio?client_date=${encodeURIComponent(localDateString())}`;
    for (let attempt = 0; attempt < 60; attempt += 1) {
        const response = await fetch(url, { credentials: 'same-origin' });
        if (response.status === 200) return URL.createObjectURL(await response.blob());
        if (response.status !== 202) throw new Error(`audio ${response.status}`);
        // Someone (often this listener) is generating the one recording; wait for it.
        status.textContent = attempt === 0
            ? 'Preparing the recording. The first listen takes up to a minute.'
            : 'Still preparing the recording…';
        const body = await response.json().catch(() => ({}));
        await sleep(Math.min(10, Math.max(2, Number(body.retry_after) || 4)) * 1000);
    }
    throw new Error('audio timeout');
}

function listenControl() {
    const status = h('p', { class: 'dvar-listen-status', role: 'status', 'aria-live': 'polite' });
    const player = h('audio', { class: 'dvar-audio', controls: '', preload: 'none' });
    player.hidden = true;
    const button = h('button', { class: 'btn btn-quiet dvar-listen-btn', type: 'button' },
        icon('speaker'), h('span', { text: 'Listen to the rebbe read it' }));

    const ready = (src) => {
        player.src = src;
        player.hidden = false;
        button.hidden = true;
        status.textContent = '';
    };
    if (audioUrl && audioFor === data.content) ready(audioUrl);

    button.addEventListener('click', async () => {
        button.disabled = true;
        status.textContent = 'Loading the recording…';
        try {
            const src = await fetchRecording(status);
            audioUrl = src;
            audioFor = data.content;
            ready(src);
            player.play().catch(() => {});
        } catch (error) {
            console.warn("D'var Torah audio unavailable:", error);
            status.textContent = 'The recording is not available right now. Please try again later.';
            button.disabled = false;
        }
    });
    return h('div', { class: 'dvar-listen' }, button, player, status);
}
