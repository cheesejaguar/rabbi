/**
 * Conversation rail: date-grouped list, client-side search, inline rename,
 * delete with undo, the account menu, desktop collapse, and the mobile
 * drawer (with an edge swipe to open).
 */
import { $, h, icon, isMobile } from './dom.js';
import { state, set } from './store.js';
import { api } from './api.js';
import { showToast } from './toast.js';
import { announce } from './a11y.js';

const UNDO_MS = 5000;

/** @type {{onOpen:(id:string)=>void, onNew:()=>void, onDeletedCurrent:()=>void, onSettings:()=>void}} */
let handlers;
let query = '';
/** @type {Map<string, {timer:number, conv:any, index:number}>} */
const pendingDeletes = new Map();

const title = (conv) => conv.title || conv.first_message || 'New conversation';
const fold = (text) => String(text || '').normalize('NFD').replace(/[̀-֑ͯ-ׇ]/g, '').toLowerCase();

function groupLabel(conv) {
    const stamp = Date.parse(conv.updated_at || conv.created_at || '');
    if (!Number.isFinite(stamp)) return '';
    const startOfToday = new Date();
    startOfToday.setHours(0, 0, 0, 0);
    const day = 86400000;
    if (stamp >= startOfToday.getTime()) return 'Today';
    if (stamp >= startOfToday.getTime() - day) return 'Yesterday';
    if (stamp >= startOfToday.getTime() - 7 * day) return 'Previous 7 days';
    if (stamp >= startOfToday.getTime() - 30 * day) return 'Previous 30 days';
    return 'Older';
}

export function renderSkeleton() {
    $('conversationsList').replaceChildren(...Array.from({ length: 4 }, () => h('div', { class: 'skeleton skeleton-row' })));
}

export function renderConversations() {
    const list = $('conversationsList');
    const all = state.conversations;
    if (!all.length) {
        list.replaceChildren(h('div', { class: 'conversations-empty', text: 'Your conversations will appear here after you ask a question.' }));
        return;
    }
    const needle = fold(query.trim());
    const visible = needle
        ? all.filter((conv) => fold(title(conv)).includes(needle) || fold(conv.first_message).includes(needle))
        : all;
    if (!visible.length) {
        list.replaceChildren(h('div', { class: 'conversations-empty', text: `No conversations match “${query.trim()}”.` }));
        return;
    }

    const nodes = [];
    let lastGroup = null;
    for (const conv of visible) {
        const group = needle ? '' : groupLabel(conv);
        if (group && group !== lastGroup) {
            nodes.push(h('p', { class: 'conversation-group', text: group }));
            lastGroup = group;
        }
        const active = conv.id === state.conversationId;
        const name = title(conv);
        nodes.push(h('div', { class: 'conversation-item' + (active ? ' active' : ''), dataset: { id: conv.id } },
            h('button', { class: 'conversation-open', type: 'button', 'aria-current': active ? 'page' : null },
                h('span', { class: 'conversation-title', dir: 'auto', text: name })),
            h('div', { class: 'conversation-menu' },
                h('button', {
                    class: 'conversation-menu-btn', type: 'button', dataset: { menuId: conv.id },
                    'aria-label': `Options for ${name}`, 'aria-haspopup': 'menu', 'aria-expanded': 'false',
                }, icon('dots')),
                h('div', { class: 'conversation-dropdown menu hidden', role: 'menu', dataset: { dropdownId: conv.id } },
                    h('button', { class: 'dropdown-item', type: 'button', role: 'menuitem', dataset: { renameId: conv.id } }, icon('pencil-simple'), 'Rename'),
                    h('button', { class: 'dropdown-item dropdown-item-danger', type: 'button', role: 'menuitem', dataset: { deleteId: conv.id } }, icon('trash'), 'Delete')))));
    }
    list.replaceChildren(...nodes);
}

export async function loadConversations({ skeleton = false } = {}) {
    if (skeleton) renderSkeleton();
    try {
        const data = await api.get('/conversations');
        const conversations = (data.conversations || []).filter((c) => !pendingDeletes.has(c.id));
        set({ conversations });
    } catch (error) {
        console.warn('Failed to load conversations:', error);
        if (skeleton) set({ conversations: [] });
    }
    renderConversations();
}

export function closeMenus() {
    document.querySelectorAll('.conversation-dropdown').forEach((menu) => menu.classList.add('hidden'));
    document.querySelectorAll('.conversation-menu-btn[aria-expanded="true"]').forEach((b) => b.setAttribute('aria-expanded', 'false'));
    $('sidebarDropdown').classList.add('hidden');
    $('userProfile').setAttribute('aria-expanded', 'false');
}

function openRowMenu(button) {
    const menu = button.parentElement.querySelector('.conversation-dropdown');
    const wasOpen = !menu.classList.contains('hidden');
    closeMenus();
    if (wasOpen) return;
    const rect = button.getBoundingClientRect();
    menu.style.top = `${Math.min(rect.bottom + 4, window.innerHeight - 110)}px`;
    menu.style.left = `${Math.max(8, rect.right - 168)}px`;
    menu.classList.remove('hidden');
    button.setAttribute('aria-expanded', 'true');
    const first = menu.querySelector('[role="menuitem"]');
    if (first) first.focus();
}

function startRename(id) {
    closeMenus();
    const row = document.querySelector(`.conversation-item[data-id="${CSS.escape(id)}"]`);
    const conv = state.conversations.find((c) => c.id === id);
    if (!row || !conv) return;
    const open = row.querySelector('.conversation-open');
    const input = h('input', { class: 'conversation-rename', type: 'text', maxlength: '200', dir: 'auto', 'aria-label': 'Conversation name' });
    input.value = title(conv);
    open.replaceWith(input);
    row.classList.add('renaming');
    input.focus();
    input.select();

    let done = false;
    const finish = async (commit) => {
        if (done) return;
        done = true;
        const next = input.value.trim();
        if (!commit || !next || next === title(conv)) {
            renderConversations();
            return;
        }
        const previous = conv.title;
        conv.title = next;
        renderConversations();
        if (id === state.conversationId) $('chatTitle').textContent = next;
        try {
            await api.patch(`/conversations/${encodeURIComponent(id)}`, { title: next });
            announce('Conversation renamed.');
        } catch {
            conv.title = previous;
            renderConversations();
            if (id === state.conversationId) $('chatTitle').textContent = title(conv);
            showToast('Could not rename the conversation.', { tone: 'error' });
        }
    };
    input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') { event.preventDefault(); finish(true); }
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); finish(false); }
    });
    input.addEventListener('blur', () => finish(true));
}

async function commitDelete(id) {
    const pending = pendingDeletes.get(id);
    if (!pending) return;
    pendingDeletes.delete(id);
    try {
        await api.del(`/conversations/${encodeURIComponent(id)}`);
    } catch {
        const list = [...state.conversations];
        list.splice(Math.min(pending.index, list.length), 0, pending.conv);
        set({ conversations: list });
        renderConversations();
        showToast('Could not delete the conversation.', { tone: 'error' });
    }
}

function deleteWithUndo(id) {
    closeMenus();
    const index = state.conversations.findIndex((c) => c.id === id);
    if (index === -1) return;
    const conv = state.conversations[index];
    set({ conversations: state.conversations.filter((c) => c.id !== id) });
    renderConversations();
    if (id === state.conversationId) handlers.onDeletedCurrent();

    const timer = window.setTimeout(() => commitDelete(id), UNDO_MS);
    pendingDeletes.set(id, { timer, conv, index });
    showToast('Conversation deleted', {
        duration: UNDO_MS,
        action: {
            label: 'Undo',
            onClick: () => {
                const pending = pendingDeletes.get(id);
                if (!pending) return;
                clearTimeout(pending.timer);
                pendingDeletes.delete(id);
                const list = [...state.conversations];
                list.splice(Math.min(pending.index, list.length), 0, pending.conv);
                set({ conversations: list });
                renderConversations();
                announce('Conversation restored.');
            },
        },
    });
}

/** Deletes that are still inside the undo window go out before unload. */
function flushPendingDeletes() {
    for (const [id, pending] of pendingDeletes) {
        clearTimeout(pending.timer);
        try {
            fetch(`/api/conversations/${encodeURIComponent(id)}`, { method: 'DELETE', keepalive: true, credentials: 'include' });
        } catch { /* best effort */ }
    }
    pendingDeletes.clear();
}

/* ---------------- Rail / drawer ---------------- */

export function setDrawerOpen(open) {
    const sidebar = $('sidebar');
    sidebar.classList.toggle('open', open);
    const overlay = $('sidebarOverlay');
    overlay.classList.toggle('visible', open);
    overlay.classList.toggle('hidden', !open);
    overlay.setAttribute('aria-hidden', String(!open));
    $('menuBtn').setAttribute('aria-expanded', String(open));
    $('welcomeMenuBtn').setAttribute('aria-expanded', String(open));
    if (open) requestAnimationFrame(() => $('newChatBtn').focus());
}

export const closeDrawer = () => setDrawerOpen(false);

function toggleCollapsed() {
    const sidebar = $('sidebar');
    sidebar.classList.toggle('collapsed');
    const expanded = !sidebar.classList.contains('collapsed');
    const toggle = $('sidebarToggle');
    toggle.setAttribute('aria-expanded', String(expanded));
    toggle.setAttribute('aria-label', expanded ? 'Collapse conversation rail' : 'Expand conversation rail');
    document.body.classList.toggle('rail-collapsed', !expanded);
    $('menuBtn').setAttribute('aria-expanded', String(expanded));
    $('welcomeMenuBtn').setAttribute('aria-expanded', String(expanded));
}

function openRail() {
    if (isMobile()) setDrawerOpen(!$('sidebar').classList.contains('open'));
    else toggleCollapsed();
}

function bindSwipe() {
    let startX = null;
    let startY = 0;
    document.addEventListener('touchstart', (event) => {
        const touch = event.touches[0];
        const open = $('sidebar').classList.contains('open');
        startX = (open || touch.clientX < 24) && isMobile() ? touch.clientX : null;
        startY = touch.clientY;
    }, { passive: true });
    document.addEventListener('touchend', (event) => {
        if (startX === null) return;
        const touch = event.changedTouches[0];
        const dx = touch.clientX - startX;
        const dy = Math.abs(touch.clientY - startY);
        const open = $('sidebar').classList.contains('open');
        if (!open && dx > 60 && dy < 50) setDrawerOpen(true);
        if (open && dx < -60 && dy < 50) setDrawerOpen(false);
        startX = null;
    }, { passive: true });
}

/** @param {typeof handlers} options */
export function initSidebar(options) {
    handlers = options;
    const list = $('conversationsList');

    list.addEventListener('click', (event) => {
        const rename = event.target.closest('[data-rename-id]');
        if (rename) { event.stopPropagation(); startRename(rename.dataset.renameId); return; }
        const del = event.target.closest('[data-delete-id]');
        if (del) { event.stopPropagation(); deleteWithUndo(del.dataset.deleteId); return; }
        const menuBtn = event.target.closest('.conversation-menu-btn');
        if (menuBtn) { event.stopPropagation(); event.preventDefault(); openRowMenu(menuBtn); return; }
        const item = event.target.closest('.conversation-item');
        if (item && !event.target.closest('.conversation-menu') && !item.classList.contains('renaming')) {
            handlers.onOpen(item.dataset.id);
        }
    });
    list.addEventListener('keydown', (event) => {
        const menu = event.target.closest('.conversation-dropdown');
        if (!menu) return;
        const items = Array.from(menu.querySelectorAll('[role="menuitem"]'));
        const index = items.indexOf(document.activeElement);
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            const next = (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
            items[next].focus();
        } else if (event.key === 'Escape') {
            event.stopPropagation();
            const button = menu.parentElement.querySelector('.conversation-menu-btn');
            closeMenus();
            button.focus();
        }
    });

    $('conversationSearch').addEventListener('input', (event) => {
        query = event.target.value;
        renderConversations();
    });
    $('conversationSearch').addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && event.target.value) {
            event.stopPropagation();
            event.target.value = '';
            query = '';
            renderConversations();
        }
    });

    $('newChatBtn').addEventListener('click', handlers.onNew);
    $('headerNewChatBtn').addEventListener('click', handlers.onNew);
    $('sidebarToggle').addEventListener('click', () => {
        if (isMobile()) closeDrawer();
        else toggleCollapsed();
    });
    $('menuBtn').addEventListener('click', openRail);
    $('welcomeMenuBtn').addEventListener('click', openRail);
    $('sidebarOverlay').addEventListener('click', closeDrawer);

    const profile = $('userProfile');
    const dropdown = $('sidebarDropdown');
    profile.addEventListener('click', (event) => {
        event.stopPropagation();
        const wasOpen = !dropdown.classList.contains('hidden');
        closeMenus();
        if (wasOpen) return;
        const rect = profile.getBoundingClientRect();
        dropdown.style.top = 'auto';
        dropdown.style.bottom = `${window.innerHeight - rect.top + 6}px`;
        dropdown.style.left = `${rect.left}px`;
        dropdown.style.width = `${Math.max(rect.width, 220)}px`;
        dropdown.classList.remove('hidden');
        profile.setAttribute('aria-expanded', 'true');
    });
    dropdown.addEventListener('click', (event) => {
        if (event.target.closest('#settingsBtn')) {
            event.stopPropagation();
            closeMenus();
            handlers.onSettings();
        }
    });
    dropdown.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') { event.stopPropagation(); closeMenus(); profile.focus(); }
    });

    document.addEventListener('click', closeMenus);
    window.addEventListener('resize', () => { if (!isMobile()) closeDrawer(); });
    window.addEventListener('pagehide', flushPendingDeletes);
    bindSwipe();
}
