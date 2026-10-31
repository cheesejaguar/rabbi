/**
 * Sources: per-message source model, the chip footer under an answer, and
 * the side panel (bottom sheet on phones) that shows passage text.
 *
 * Two kinds are kept visibly distinct, per PRODUCT.md:
 *  - "From the library": passages retrieved for this answer (citation events,
 *    or metadata.sources with verified=true).
 *  - "General knowledge": references the model supplied that were not matched
 *    against the library (metadata.sources with verified=false).
 */
import { $, h, icon, isMobile } from '../dom.js';

/**
 * @typedef {{n?:number, kind:'library'|'general', ref:string, title?:string, url?:string, excerpt?:string}} SourceItem
 */

const norm = (value) => String(value || '').trim().toLowerCase();

/**
 * @param {Map<number, any>} citations  n -> citation source payload
 * @param {Array<any>} metaSources      metadata.sources
 * @returns {SourceItem[]}
 */
export function buildSourceItems(citations, metaSources) {
    /** @type {SourceItem[]} */
    const items = [];
    const seen = new Set();
    const numbered = [...citations.entries()].sort((a, b) => a[0] - b[0]);
    for (const [n, src] of numbered) {
        const ref = src.ref || src.title || `Source ${n}`;
        items.push({ n, kind: 'library', ref, title: src.title, url: src.url, excerpt: src.excerpt });
        seen.add(norm(ref));
        if (src.title) seen.add(norm(src.title));
    }
    for (const raw of metaSources || []) {
        const src = typeof raw === 'string' ? { ref: raw, verified: false } : (raw || {});
        const ref = src.ref || src.title;
        if (!ref) continue;
        if (Number.isFinite(Number(src.n)) && !citations.has(Number(src.n))) {
            items.push({ n: Number(src.n), kind: 'library', ref, title: src.title, url: src.url, excerpt: src.excerpt });
            seen.add(norm(ref));
            continue;
        }
        if (seen.has(norm(ref))) continue;
        seen.add(norm(ref));
        const library = src.kind === 'library' || src.verified === true;
        items.push({ kind: library ? 'library' : 'general', ref, title: src.title, url: src.url, excerpt: src.excerpt });
    }
    return items.sort((a, b) => {
        if (a.kind !== b.kind) return a.kind === 'library' ? -1 : 1;
        if (a.n && b.n) return a.n - b.n;
        if (a.n) return -1;
        if (b.n) return 1;
        return 0;
    });
}

export const KIND_LABEL = { library: 'From the library', general: 'General knowledge' };

/**
 * Footer of chips under an answer. Returns null when there is nothing to show.
 * @param {SourceItem[]} items
 * @param {(index:number, trigger:HTMLElement)=>void} onOpen
 */
export function sourcesFooter(items, onOpen) {
    if (!items.length) return null;
    const footer = h('div', { class: 'message-sources' });
    footer.append(h('span', { class: 'sources-label', text: 'Sources' }));
    for (const kind of ['library', 'general']) {
        const group = items.map((item, index) => ({ item, index })).filter(({ item }) => item.kind === kind);
        if (!group.length) continue;
        const row = h('div', { class: `sources-group sources-group-${kind}`, role: 'group', 'aria-label': KIND_LABEL[kind] });
        row.append(h('span', { class: `source-kind source-kind-${kind}` },
            icon(kind === 'library' ? 'books' : 'info'),
            KIND_LABEL[kind]));
        for (const { item, index } of group) {
            const chip = h('button', {
                type: 'button',
                class: `source-chip ${kind === 'library' ? 'local-match' : 'model-knowledge'}`,
                dir: 'auto',
                'aria-label': `${item.n ? `Source ${item.n}: ` : ''}${item.ref}, ${KIND_LABEL[kind].toLowerCase()}`,
            },
            item.n ? h('span', { class: 'source-num numeric', 'aria-hidden': 'true', text: String(item.n) }) : null,
            h('span', { class: 'source-ref', text: item.ref }));
            chip.addEventListener('click', () => onOpen(index, chip));
            row.append(chip);
        }
        footer.append(row);
    }
    return footer;
}

/* ---------------- Panel ---------------- */

let returnFocus = null;

function sourceLinkLabel(url) {
    try {
        return new URL(url).hostname.replace(/^www\./, '').includes('sefaria.org') ? 'Open on Sefaria' : 'Open source';
    } catch {
        return 'Open source';
    }
}

function renderPanel(items, highlight) {
    const list = $('sourcesList');
    list.replaceChildren();
    items.forEach((item, index) => {
        const li = h('li', {
            class: `source-item source-item-${item.kind}` + (index === highlight ? ' highlighted' : ''),
            id: `source-item-${index}`,
            tabindex: '-1',
        });
        const head = h('div', { class: 'source-item-head' },
            item.n ? h('span', { class: 'source-num numeric', text: String(item.n) }) : null,
            h('span', { class: `source-kind source-kind-${item.kind}` },
                icon(item.kind === 'library' ? 'books' : 'info'), KIND_LABEL[item.kind]));
        li.append(head);
        li.append(h('p', { class: 'source-item-ref', dir: 'auto', text: item.ref }));
        if (item.title && item.title !== item.ref) {
            li.append(h('p', { class: 'source-item-title', dir: 'auto', text: item.title }));
        }
        if (item.excerpt) {
            li.append(h('blockquote', { class: 'source-excerpt', dir: 'auto', text: item.excerpt }));
        } else if (item.kind === 'general') {
            li.append(h('p', { class: 'source-note', text: 'Cited from general knowledge. Not matched against the library; check the original before relying on it.' }));
        }
        if (item.url && /^https?:\/\//i.test(item.url)) {
            li.append(h('a', { class: 'source-link', href: item.url, target: '_blank', rel: 'noopener noreferrer' },
                sourceLinkLabel(item.url), icon('arrow-up-right'),
                h('span', { class: 'sr-only', text: ' (opens in a new tab)' })));
        }
        list.append(li);
    });
}

export function openSourcesPanel(items, highlight = 0, trigger = null) {
    const panel = $('sourcesPanel');
    returnFocus = trigger || (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    renderPanel(items, highlight);
    panel.hidden = false;
    document.body.classList.add('sources-open');
    const overlay = $('panelOverlay');
    overlay.classList.toggle('hidden', !isMobile() && window.innerWidth > 1180);
    requestAnimationFrame(() => {
        panel.classList.add('open');
        const target = document.getElementById(`source-item-${highlight}`);
        if (target) {
            target.scrollIntoView({ block: 'nearest' });
            target.focus({ preventScroll: true });
        } else {
            $('closeSourcesPanel').focus();
        }
    });
}

export function closeSourcesPanel() {
    const panel = $('sourcesPanel');
    if (panel.hidden) return;
    panel.classList.remove('open');
    document.body.classList.remove('sources-open');
    $('panelOverlay').classList.add('hidden');
    panel.hidden = true;
    if (returnFocus && document.contains(returnFocus)) returnFocus.focus();
    returnFocus = null;
}

export const sourcesPanelOpen = () => !$('sourcesPanel').hidden;

export function initSourcesPanel() {
    $('closeSourcesPanel').addEventListener('click', closeSourcesPanel);
    $('panelOverlay').addEventListener('click', closeSourcesPanel);
    $('sourcesPanel').addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            event.stopPropagation();
            closeSourcesPanel();
        }
    });
}
