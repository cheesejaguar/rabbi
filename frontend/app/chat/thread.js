/**
 * The scrolling message list: stick-to-bottom while the reader is at the
 * bottom, a "jump to latest" pill when they are not, and per-conversation
 * scroll restore.
 */
import { prefersReducedMotion } from '../dom.js';

const PIN_THRESHOLD = 48;

export class Thread {
    /**
     * @param {HTMLElement} scroller  element that scrolls
     * @param {HTMLElement} list      message container inside it
     * @param {HTMLElement} pill      jump-to-latest button
     */
    constructor(scroller, list, pill) {
        this.scroller = scroller;
        this.list = list;
        this.pill = pill;
        this.pinned = true;
        /** @type {Map<string, number>} */
        this.positions = new Map();

        // Only a reader's own gesture may unpin. A scroll event caused by our
        // own pinning can land after more tokens have grown the list, which
        // would otherwise read as "the reader scrolled away".
        let intentUntil = 0;
        const intent = () => { intentUntil = performance.now() + 700; };
        scroller.addEventListener('wheel', intent, { passive: true });
        scroller.addEventListener('touchmove', intent, { passive: true });
        scroller.addEventListener('pointerdown', intent);
        scroller.addEventListener('keydown', intent);
        scroller.addEventListener('scroll', () => {
            if (this.distanceFromBottom() <= PIN_THRESHOLD) this.pinned = true;
            else if (performance.now() < intentUntil) this.pinned = false;
            this.updatePill();
        }, { passive: true });

        // Growth from streamed tokens, safety cards, or images keeps the
        // view pinned only if the reader was already at the bottom.
        if ('ResizeObserver' in window) {
            this.resizer = new ResizeObserver(() => {
                if (this.pinned) this.scroller.scrollTop = this.scroller.scrollHeight;
                this.updatePill();
            });
            this.resizer.observe(list);
        }

        pill.addEventListener('click', () => this.scrollToBottom({ smooth: true }));
    }

    distanceFromBottom() {
        const s = this.scroller;
        return s.scrollHeight - s.scrollTop - s.clientHeight;
    }

    updatePill() {
        const away = !this.pinned && this.distanceFromBottom() > 160;
        this.pill.classList.toggle('hidden', !away);
    }

    /** Called on every streaming frame. */
    grew() {
        if (this.pinned) this.scroller.scrollTop = this.scroller.scrollHeight;
        else this.updatePill();
    }

    scrollToBottom({ smooth = false } = {}) {
        this.pinned = true;
        const top = this.scroller.scrollHeight;
        if (smooth && !prefersReducedMotion()) this.scroller.scrollTo({ top, behavior: 'smooth' });
        else this.scroller.scrollTop = top;
        this.updatePill();
    }

    /** Keep an element's top in view and stop following the stream. */
    reveal(el) {
        requestAnimationFrame(() => {
            const top = el.getBoundingClientRect().top - this.scroller.getBoundingClientRect().top + this.scroller.scrollTop - 12;
            this.pinned = false;
            this.scroller.scrollTop = Math.max(0, top);
            this.updatePill();
        });
    }

    append(el) {
        this.list.append(el);
        this.markLast();
    }

    clear() {
        this.list.replaceChildren();
        this.pinned = true;
        this.updatePill();
    }

    /** Only the final user/assistant messages get edit/regenerate controls. */
    markLast() {
        this.list.querySelectorAll('.message.is-last').forEach((el) => el.classList.remove('is-last'));
        const users = this.list.querySelectorAll('.message.user');
        const assistants = this.list.querySelectorAll('.message.assistant');
        const lastUser = users[users.length - 1];
        const lastAssistant = assistants[assistants.length - 1];
        if (lastUser) lastUser.classList.add('is-last');
        if (lastAssistant && (!lastUser || lastUser.compareDocumentPosition(lastAssistant) & Node.DOCUMENT_POSITION_FOLLOWING)) {
            lastAssistant.classList.add('is-last');
        }
    }

    savePosition(key) {
        if (!key) return;
        this.positions.set(key, this.pinned ? -1 : this.scroller.scrollTop);
    }

    restorePosition(key) {
        const saved = key ? this.positions.get(key) : undefined;
        requestAnimationFrame(() => {
            if (saved === undefined || saved === -1) this.scrollToBottom();
            else {
                this.scroller.scrollTop = saved;
                this.pinned = this.distanceFromBottom() <= PIN_THRESHOLD;
                this.updatePill();
            }
        });
    }
}
