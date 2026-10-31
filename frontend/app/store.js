/**
 * Minimal observable state. Modules read `state` directly and call
 * `set()` to change it; subscribers receive the changed keys.
 */

export const state = {
    /** @type {{id:string, first_name?:string, last_name?:string, email?:string, is_admin?:boolean}|null} */
    user: null,
    /** @type {{chats_remaining:number}|null} */
    guestStatus: null,
    /** @type {{credits:number, unlimited:boolean, tts_credit_cost?:number}|null} */
    credits: null,
    /** @type {Array<{id:string, title?:string, first_message?:string, updated_at?:string, created_at?:string}>} */
    conversations: [],
    /** @type {string|null} */
    conversationId: null,
    /** @type {string|null} */
    sessionId: null,
    /** Guest-only rolling history (signed-in history is loaded server-side). */
    history: [],
    streaming: false,
    /** True while the current turn carries safety resources. */
    crisisTurn: false,
};

const listeners = new Set();

/** @param {Partial<typeof state>} patch */
export function set(patch) {
    const changed = [];
    for (const [key, value] of Object.entries(patch)) {
        if (state[key] !== value) {
            state[key] = value;
            changed.push(key);
        }
    }
    if (changed.length) listeners.forEach((fn) => fn(changed, state));
}

/** @param {(changed:string[], s:typeof state)=>void} fn */
export function subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
}

export const HISTORY_CAP = 20;

export function pushHistory(role, content) {
    const next = [...state.history, { role, content }].slice(-HISTORY_CAP);
    state.history = next;
}
