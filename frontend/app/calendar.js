/**
 * Shabbat / yom tov awareness banner, based on the reader's local clock.
 * Dismissal is remembered per message for the browser session.
 */
import { $, h, icon, localDateString, session } from './dom.js';

export async function checkCalendarStatus() {
    try {
        const now = new Date();
        const pad = (n) => String(n).padStart(2, '0');
        const localTime = `${localDateString(now)}T${pad(now.getHours())}:${pad(now.getMinutes())}:00`;
        const response = await fetch(`/api/calendar-status?client_time=${encodeURIComponent(localTime)}`);
        if (!response.ok) return;
        const data = await response.json();
        const banner = $('calendarBanner');
        if (!banner || !data.message) return;
        if (session.get('calendarBannerDismissed') === data.message) return;
        const close = h('button', { class: 'icon-btn calendar-banner-close', type: 'button', 'aria-label': 'Dismiss notice' }, icon('x'));
        close.addEventListener('click', () => {
            banner.classList.add('hidden');
            session.set('calendarBannerDismissed', data.message);
        });
        banner.replaceChildren(icon('moon'), h('span', { class: 'calendar-banner-text', dir: 'auto', text: data.message }), close);
        banner.classList.remove('hidden');
    } catch (error) {
        console.warn('Calendar status check failed:', error);
    }
}
