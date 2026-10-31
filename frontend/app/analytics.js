/**
 * Fire-and-forget analytics. Event names are a stable contract with the
 * admin dashboard (session_start, page_view, and the TTS lifecycle).
 */
import { session } from './dom.js';

const API = '/api';

let analyticsSessionId = session.get('analyticsSessionId');
if (!analyticsSessionId) {
    analyticsSessionId = 'sess_' + Date.now() + '_' + Math.random().toString(36).slice(2, 11);
    session.set('analyticsSessionId', analyticsSessionId);
}

export async function trackEvent(eventType, eventData = {}, pagePath = null) {
    try {
        await fetch(`${API}/analytics`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            keepalive: true,
            body: JSON.stringify({
                session_id: analyticsSessionId,
                event_type: eventType,
                event_data: eventData,
                page_path: pagePath || window.location.pathname,
                referrer: document.referrer || null,
            }),
        });
    } catch {
        // Analytics must never break the app.
    }
}

export async function trackTTSEvent(eventType, messageId = null, textLength = null, durationMs = null, errorMessage = null) {
    try {
        await fetch(`${API}/tts-event`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                event_type: eventType,
                message_id: messageId,
                text_length: textLength,
                duration_ms: durationMs,
                error_message: errorMessage,
            }),
        });
    } catch {
        // Analytics must never break the app.
    }
}

export function trackSessionStart() {
    if (!session.get('sessionTracked')) {
        trackEvent('session_start', { new_session: true });
        session.set('sessionTracked', 'true');
    }
    trackEvent('page_view');
}
