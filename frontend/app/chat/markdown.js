/**
 * Streaming markdown: markdown-it + DOMPurify (both vendored, pinned).
 *
 * The full text is re-parsed on every frame (cheap at chat sizes), split into
 * top-level blocks, and only blocks whose source changed are re-rendered.
 * Finished paragraphs, lists, and headings therefore keep their DOM nodes, so
 * nothing above the live block flickers or re-flows while tokens arrive.
 *
 * Citation markers are spliced into the source as private-use sentinels
 * (U+E000 n U+E001), survive markdown parsing as inert text, and are swapped
 * for superscript buttons after rendering and before sanitizing.
 */
import markdownit from '../../vendor/markdown-it.esm.js';
import DOMPurify from '../../vendor/purify.es.js';

const md = markdownit({ html: false, linkify: true, breaks: true, typographer: false });

const OPEN = '';
const CLOSE = '';
const MARKER = /(\d{1,3})/g;
const BLOCK_TAGS = new Set(['P', 'LI', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'BLOCKQUOTE', 'TD', 'TH', 'DT', 'DD']);

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (node.tagName === 'A' && node.hasAttribute('href')) {
        node.setAttribute('target', '_blank');
        node.setAttribute('rel', 'noopener noreferrer');
    }
    if (BLOCK_TAGS.has(node.tagName)) node.setAttribute('dir', 'auto');
});

const PURIFY = {
    RETURN_DOM_FRAGMENT: true,
    FORBID_TAGS: ['style', 'form', 'input', 'textarea', 'select', 'iframe', 'img', 'svg', 'math'],
    FORBID_ATTR: ['style'],
};

/** Neutralise any sentinel characters the model itself emitted. */
const stripSentinels = (text) => text.replace(/[]/g, '');

/**
 * Splice citation markers into text at their character offsets.
 * @param {string} text
 * @param {Array<{n:number, offset:number}>} citations
 */
export function withCitationMarkers(text, citations) {
    let out = stripSentinels(text || '');
    if (!citations || !citations.length) return out;
    const sorted = [...citations]
        .filter((c) => Number.isFinite(Number(c.n)))
        .sort((a, b) => (b.offset ?? out.length) - (a.offset ?? out.length));
    for (const { n, offset } of sorted) {
        const at = Math.max(0, Math.min(out.length, Number.isFinite(offset) ? offset : out.length));
        out = out.slice(0, at) + OPEN + n + CLOSE + out.slice(at);
    }
    return out;
}

function markerHtml(_match, n) {
    return `<sup class="cite"><button type="button" class="cite-marker" data-cite="${n}" aria-label="Source ${n}">${n}</button></sup>`;
}

/** Sanitize rendered HTML into a fragment and apply presentational wrappers. */
function toFragment(html) {
    const fragment = DOMPurify.sanitize(html.replace(MARKER, markerHtml), PURIFY);
    fragment.querySelectorAll('table').forEach((table) => {
        const wrap = document.createElement('div');
        wrap.className = 'table-wrap';
        wrap.tabIndex = 0;
        table.replaceWith(wrap);
        wrap.append(table);
    });
    fragment.querySelectorAll('pre').forEach((pre) => {
        const wrap = document.createElement('div');
        wrap.className = 'code-block';
        const copy = document.createElement('button');
        copy.type = 'button';
        copy.className = 'code-copy';
        copy.dataset.action = 'copy-code';
        copy.textContent = 'Copy';
        pre.replaceWith(wrap);
        wrap.append(copy, pre);
    });
    return fragment;
}

/** Render a complete markdown string (with optional citation offsets). */
export function renderMarkdown(text, citations) {
    return toFragment(md.render(withCitationMarkers(text, citations)));
}

/**
 * @param {string} text source with sentinels already spliced in
 * @returns {{blocks: Array<{src:string, tokens:any[]}>, env:object}}
 */
function splitBlocks(text) {
    const env = {};
    const tokens = md.parse(text, env);
    const lines = text.split('\n');
    const blocks = [];
    let current = null;
    for (const token of tokens) {
        if (token.level === 0 && token.nesting !== -1 && token.map) {
            const [start, end] = token.map;
            current = { src: lines.slice(start, end).join('\n'), tokens: [] };
            blocks.push(current);
        }
        if (current) current.tokens.push(token);
    }
    return { blocks, env };
}

/**
 * Incremental renderer bound to one message body element.
 */
export class StreamingMarkdown {
    /** @param {HTMLElement} container */
    constructor(container) {
        this.container = container;
        /** @type {Array<{src:string, nodes:Node[]}>} */
        this.rendered = [];
    }

    /** @param {string} text  source with citation sentinels already spliced */
    update(text) {
        const { blocks, env } = splitBlocks(text);
        for (let i = 0; i < blocks.length; i += 1) {
            const block = blocks[i];
            const previous = this.rendered[i];
            if (previous && previous.src === block.src) continue;
            const fragment = toFragment(md.renderer.render(block.tokens, md.options, env));
            const nodes = Array.from(fragment.childNodes).filter(
                (node) => node.nodeType !== 3 || node.textContent.trim(),
            );
            const anchor = previous ? previous.nodes[0] : null;
            if (anchor && anchor.parentNode === this.container) {
                this.container.insertBefore(fragment, anchor);
                previous.nodes.forEach((node) => node.remove());
            } else {
                // Previous block had no nodes (or none yet): append after the
                // last rendered block to keep order.
                const after = this.lastNodeBefore(i);
                if (after && after.nextSibling) this.container.insertBefore(fragment, after.nextSibling);
                else this.container.append(fragment);
                if (previous) previous.nodes.forEach((node) => node.remove());
            }
            this.rendered[i] = { src: block.src, nodes };
        }
        for (let i = blocks.length; i < this.rendered.length; i += 1) {
            this.rendered[i].nodes.forEach((node) => node.remove());
        }
        this.rendered.length = blocks.length;
    }

    lastNodeBefore(index) {
        for (let i = index - 1; i >= 0; i -= 1) {
            const nodes = this.rendered[i] && this.rendered[i].nodes;
            if (nodes && nodes.length) return nodes[nodes.length - 1];
        }
        return null;
    }

    reset() {
        this.container.replaceChildren();
        this.rendered = [];
    }
}

export const sentinel = { OPEN, CLOSE, strip: stripSentinels };
