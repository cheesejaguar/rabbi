Warning: truncated output (original token count: 34379)
Total output lines: 3441

/**
 * @file rebbe.dev - Frontend Application
 * @description Single-page application for Torah wisdom chatbot with streaming chat,
 *              text-to-speech, Stripe payments, conversation management, and analytics.
 * @version 1.0.0
 */

/* ============================================================
 * CONFIGURATION & STATE
 * Global constants, application state variables, and session
 * identifiers used throughout the application lifecycle.
 * ============================================================ */

/** @type {string} Base path for all API endpoints */
const API_BASE = '/api';

/** @type {Array<{role: string, content: string}>} Conversation message history, capped at 20 messages */
let conversationHistory = [];
/** @type {string|null} Server-assigned session identifier for the current chat stream */
let sessionId = null;
/** @type {string|null} UUID of the currently active conversation (null for guests or new chats) */
let currentConversationId = null;
/** @type {Array<{id: string, title: string, first_message: string}>} List of all user conversations loaded from the server */
let conversations = [];
/** @type {boolean} Whether a chat message is currently being sent/streamed */
let isLoading = false;
/** @type {{first_name: string, last_name: string, email: string}|null} Authenticated user object, null when logged out or guest */
let currentUser = null;
/** @type {{chats_remaining: number}|null} Guest chat allowance tracker for unauthenticated users */
let guestStatus = null;

/** @type {string} Analytics session ID that persists across page loads within the same browser session */
let analyticsSessionId = sessionStorage.getItem('analyticsSessionId');
// Generate a new analytics session ID if one does not already exist in sessionStorage.
// Format: "sess_<timestamp>_<random alphanumeric>" to ensure uniqueness.
if (!analyticsSessionId) {
    analyticsSessionId = 'sess_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    sessionStorage.setItem('analyticsSessionId', analyticsSessionId);
}

/* ============================================================
 * ANALYTICS
 * Functions for tracking user events and text-to-speech usage.
 * All analytics calls fail silently to avoid disrupting the UX.
 * ============================================================ */

/**
 * @description Sends a generic analytics event to the server. Failures are silently
 *              ignored so analytics never interfere with the user experience.
 * @param {string} eventType - The type of event (e.g., 'session_start', 'page_view')
 * @param {Object} [eventData={}] - Additional event metadata
 * @param {string|null} [pagePath=null] - Override for the current page path; defaults to window.location.pathname
 * @returns {Promise<void>}
 * @async
 */
async function trackEvent(eventType, eventData = {}, pagePath = null) {
    try {
        await fetch(`${API_BASE}/analytics`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: analyticsSessionId,
                event_type: eventType,
                event_data: eventData,
                page_path: pagePath || window.location.pathname,
                referrer: document.referrer || null
            })
        });
    } catch (e) {
        // Silently fail - analytics should never break the app
    }
}

/**
 * @description Tracks a text-to-speech lifecycle event (start, stop, complete, error).
 *              Used to monitor TTS feature usage and diagnose failures.
 * @param {string} eventType - One of 'start', 'stop', 'complete', or 'error'
 * @param {string|null} [messageId=null] - The database ID of the message being spoken
 * @param {number|null} [textLength=null] - Character length of the text being converted to speech
 * @param {number|null} [durationMs=null] - Total playback duration in milliseconds (for 'complete' events)
 * @param {string|null} [errorMessage=null] - Error description (for 'error' events)
 * @returns {Promise<void>}
 * @async
 */
async function trackTTSEvent(eventType, messageId = null, textLength = null, durationMs = null, errorMessage = null) {
    try {
        await fetch(`${API_BASE}/tts-event`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                event_type: eventType,
                message_id: messageId,
                text_length: textLength,
                duration_ms: durationMs,
                error_message: errorMessage
            })
        });
    } catch (e) {
        // Silently fail - TTS analytics should never break the app
    }
}

/* ============================================================
 * DOM REFERENCES
 * Cached references to DOM elements used throughout the app.
 * Organized by screen/feature area for maintainability.
 * ============================================================ */

// --- Main screen elements ---
/** @type {HTMLElement} */
const welcomeScreen = document.getElementById('welcomeScreen');
/** @type {HTMLElement} */
const chatScreen = document.getElementById('chatScreen');
/** @type {HTMLElement} */
const greetingText = document.getElementById('greetingText');
/** @type {HTMLElement} Skeleton placeholder shown while the greeting is loading */
const greetingSkeleton = document.getElementById('greetingSkeleton');
/** @type {HTMLTextAreaElement} Welcome screen message textarea */
const messageInput = document.getElementById('messageInput');
/** @type {HTMLButtonElement} Welcome screen send button */
const sendBtn = document.getElementById('sendBtn');
/** @type {HTMLTextAreaElement} Chat screen message textarea */
const chatInput = document.getElementById('chatInput');
/** @type {HTMLButtonElement} Chat screen send button */
const chatSendBtn = document.getElementById('chatSendBtn');
/** @type {HTMLElement} Scrollable container for chat message bubbles */
const chatMessages = document.getElementById('chatMessages');
/** @type {HTMLElement} */
const chatTitle = document.getElementById('chatTitle');
/** @type {HTMLElement} Banner suggesting the user consult a human rabbi */
const referralNotice = document.getElementById('referralNotice');
/** @type {HTMLElement} */
const loadingIndicator = document.getElementById('loadingIndicator');
/** @type {NodeListOf<HTMLElement>} Preset prompt suggestion chips on the welcome screen */
const suggestionChips = document.querySelectorAll('.suggestion-chip');

// --- Sidebar elements ---
/** @type {HTMLElement} */
const sidebar = document.getElementById('sidebar');
/** @type {HTMLElement} */
const sidebarToggle = document.getElementById('sidebarToggle');
/** @type {HTMLElement} Translucent overlay shown behind the sidebar on mobile */
const sidebarOverlay = document.getElementById('sidebarOverlay');
/** @type {HTMLElement} Hamburger menu button on the chat screen header */
const menuBtn = document.getElementById('menuBtn');
/** @type {HTMLElement} Hamburger menu button on the welcome screen header */
const welcomeMenuBtn = document.getElementById('welcomeMenuBtn');
/** @type {HTMLElement} */
const newChatBtn = document.getElementById('newChatBtn');
/** @type {HTMLElement} Container for the rendered conversation list items */
const conversationsList = document.getElementById('conversationsList');
/** @type {HTMLElement} */
const sidebarUserAvatar = document.getElementById('sidebarUserAvatar');
/** @type {HTMLElement} */
const sidebarUserName = document.getElementById('sidebarUserName');
/** @type {HTMLElement} Clickable user profile area at the bottom of the sidebar */
const userProfile = document.getElementById('userProfile');
/** @type {HTMLElement} */
const sidebarUserMenuToggle = document.getElementById('sidebarUserMenuToggle');
/** @type {HTMLElement} Dropdown menu positioned above the user profile (Settings, Logout) */
const sidebarDropdown = document.getElementById('sidebarDropdown');
/** @type {HTMLElement} */
const settingsScreen = document.getElementById('settingsScreen');
/** @type {HTMLElement} */
const settingsBtn = document.getElementById('settingsBtn');
/** @type {HTMLElement} */
const settingsBackBtn = document.getElementById('settingsBackBtn');
const languageDefaultSelect = document.getElementById('languageDefaultSelect');
/** @type {HTMLElement} Displays the user's current credit balance */
const creditsValue = document.getElementById('creditsValue');
/** @type {HTMLElement} */
const settingsUserName = document.getElementById('settingsUserName');
/** @type {HTMLElement} */
const settingsUserEmail = document.getElementById('settingsUserEmail');
/** @type {HTMLSelectElement} */
const denominationSelect = document.getElementById('denominationSelect');
/** @type {HTMLTextAreaElement} */
const bioInput = document.getElementById('bioInput');
/** @type {HTMLElement} */
const bioCharCount = document.getElementById('bioCharCount');
/** @type {HTMLButtonElement} */
const saveProfileBtn = document.getElementById('saveProfileBtn');

// --- D'var Torah elements ---
/** @type {HTMLElement} */
const dvarTorahSection = document.getElementById('dvarTorahSection');
/** @type {HTMLElement} Skeleton placeholder shown while the d'var Torah preview is loading */
const dvarTorahSkeleton = document.getElementById('dvarTorahSkeleton');
/** @type {HTMLElement} */
const dvarTorahParsha = document.getElementById('dvarTorahParsha');
/** @type {HTMLElement} */
const dvarTorahPreview = document.getElementById('dvarTorahPreview');
/** @type {HTMLElement} */
const dvarTorahExpandBtn = document.getElementById('dvarTorahExpandBtn');
/** @type {HTMLElement} */
const dvarTorahScreen = document.getElementById('dvarTorahScreen');
/** @type {HTMLElement} */
const dvarTorahBackBtn = document.getElementById('dvarTorahBackBtn');
/** @type {HTMLElement} */
const dvarTorahScreenTitle = document.getElementById('dvarTorahScreenTitle');
/** @type {HTMLElement} */
const dvarTorahScreenContent = document.getElementById('dvarTorahScreenContent');
/** @type {{parsha_name: string, parsha_name_hebrew: string, content: string, is_holiday_week: boolean}|null} Cached weekly Torah portion data */
let dvarTorahData = null;

// --- Payment modal elements ---
/** @type {HTMLElement} */
const purchaseModal = document.getElementById('purchaseModal');
/** @type {HTMLElement} */
const buyCreditsBtn = document.getElementById('buyCreditsBtn');
/** @type {HTMLElement} */
const closePurchaseModal = document.getElementById('closePurchaseModal');
/** @type {NodeListOf<HTMLElement>} Credit package option cards (e.g., 10 credits, 25 credits) */
const packageCards = document.querySelectorAll('#packageSelection .package-card[data-package]');
/** @type {HTMLButtonElement} */
const submitPayment = document.getElementById('submitPayment');
/** @type {HTMLElement} Mount point for the Stripe PaymentElement */
const paymentElementContainer = document.getElementById('paymentElementContainer');
/** @type {HTMLElement} */
const packageSelection = document.getElementById('packageSelection');
/** @type {HTMLElement} */
const modalFooter = document.getElementById('modalFooter');
/** @type {HTMLElement} */
const paymentStatus = document.getElementById('paymentStatus');
/** @type {HTMLElement} */
const paymentSuccess = document.getElementById('paymentSuccess');
/** @type {HTMLElement} */
const paymentError = document.getElementById('paymentError');
/** @type {HTMLElement} */
const paymentErrorMessage = document.getElementById('paymentErrorMessage');
/** @type {HTMLElement} Polite screen-reader announcement region */
const appLiveRegion = document.getElementById('appLiveRegion');

// --- Stripe payment state ---
/** @type {Object|null} Stripe.js instance, initialized lazily on first modal open */
let stripe = null;
/** @type {Object|null} Stripe Elements instance bound to the current PaymentIntent client secret */
let elements = null;
/** @type {Object|null} Stripe PaymentElement mounted inside the purchase modal */
let paymentElement = null;
/** @type {string} Currently selected credit package identifier (e.g., 'credits_10', 'credits_25') */
let selectedPackage = 'credits_10';
/** @type {boolean} Whether new chat content should keep following the bottom edge */
let shouldAutoScroll = true;
/** @type {WeakMap<HTMLElement, {content: string, frame: number|null}>} */
const streamingRenderState = new WeakMap();

/* ============================================================
 * INITIALIZATION
 * Entry point that bootstraps the application on DOMContentLoaded.
 * Sets up event listeners, checks authentication, loads greeting
 * and D'var Torah, and restores conversation state.
 * ============================================================ */

document.addEventListener('DOMContentLoaded', init);

/**
 * @description Main initialization function. Runs on DOMContentLoaded. Sets up the UI
 *              in logged-out state immediately (for fast first paint), attaches all event
 *              listeners, fires analytics, checks auth, loads greeting/D'var Torah,
 *              and restores conversations for authenticated users.
 * @returns {Promise<void>}
 * @async
 */
async function init() {
    // Show logged-out state immediately (will be updated if authenticated)
    showLoggedOutState();

    // Setup event listeners immediately so UI is responsive
    setupEventListeners();

    // Track session start (only once per browser session)
    if (!sessionStorage.getItem('sessionTracked')) {
        trackEvent('session_start', { new_session: true });
        sessionStorage.setItem('sessionTracked', 'true');
    }
    // Always track page view
    trackEvent('page_view');

    // Check authentication
    const isAuthenticated = await checkAuth();
    if (isAuthenticated) await loadAccountLanguage();

    // Shabbat / yom tov awareness banner (fire-and-forget)
    checkCalendarStatus();

    // Load greeting and d'var Torah for all users (authenticated and guests)
    await Promise.all([loadGreeting(), loadDvarTorah()]);

    if (!isAuthenticated) {
        // Check guest status for non-authenticated users
        await checkGuestStatus();
        return;
    }

    // Check for payment success redirect (from external payment methods like Amazon Pay)
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('payment') === 'success') {
        // Clear the URL parameter
        window.history.replaceState({}, '', window.location.pathname);
        // Show success message
        showToast('Payment successful! Credits have been added to your account.');
    }

    // Check for sponsorship success redirect (same redirect-based payment
    // methods as above, but for d'var Torah dedications)
    if (urlParams.get('sponsorship') === 'success') {
        const paymentIntentId = urlParams.get('payment_intent');
        window.history.replaceState({}, '', window.location.pathname);

        // Best-effort immediate fulfillment (dev-only endpoint; production
        // relies on webhooks, where this returns 404 and is safely ignored)
        if (paymentIntentId) {
            try {
                await fetch(`${API_BASE}/payments/verify-and-fulfill`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ payment_intent_id: paymentIntentId }),
                    credentials: 'include',
                });
            } catch (verifyError) {
                console.error('Sponsorship verification error:', verifyError);
            }
        }

        showToast("Thank you! Your d'var Torah dedication has been received.");
        // Refresh so the new dedication appears once fulfillment lands
        await loadDvarTorah(true);
    }

    // If the user was mid-prompt before logging in, restore their draft
    restorePendingDraft();

    await loadConversations();
}

/* ============================================================
 * AUTHENTICATION
 * Functions for checking auth state, managing guest sessions,
 * and toggling the UI between logged-in and logged-out states.
 * ============================================================ */

/**
 * @description Fetches the guest chat allowance from the server. Used for
 *              unauthenticated users to determine how many free chats remain.
 * @returns {Promise<{chats_remaining: number}|null>} Guest status object or null on failure
 * @async
 */
async function checkGuestStatus() {
    try {
        const response = await fetch(`${API_BASE}/guest/status`);
        if (response.ok) {
            guestStatus = await response.json();
            return guestStatus;
        }
    } catch (error) {
        console.error('Failed to check guest status:', error);
    }
    return null;
}

/**
 * @description Checks the user's authentication status by calling the /auth/check endpoint.
 *              If authenticated, stores the user object and updates the sidebar UI.
 * @returns {Promise<boolean>} True if the user is authenticated, false otherwise
 * @async
 */
async function checkAuth() {
    try {
        const response = await fetch('/auth/check');
        if (response.ok) {
            const data = await response.json();
            currentUser = data.user;
            updateUserUI();
            return data.authenticated;
        }
        return false;
    } catch (error) {
        console.error('Auth check failed:', error);
        return false;
    }
}

/**
 * @description Updates the sidebar and dropdown UI to reflect the authenticated user's
 *              name, initials avatar, and available menu options (Settings, Logout).
 *              Re-attaches the settings button listener since the dropdown HTML is replaced.
 * @returns {void}
 */
function updateUserUI() {
    if (!currentUser) return;

    sidebarUserAvatar.classList.remove('ph-icon', 'ph-arrow-right');
    const firstName = currentUser.first_name || '';
    const lastName = currentUser.last_name || '';
    const email = currentUser.email || '';
    const fullName = [firstName, lastName].filter(Boolean).join(' ') || 'User';
    const initials = getInitials(firstName, lastName, email);

    // Update sidebar user info
    updateTextWithFade(sidebarUserAvatar, initials);
    sidebarUserAvatar.style.fontSize = '';  // Reset font size from logged-out state
    updateTextWithFade(sidebarUserName, fullName);

    // Restore logged-in dropdown content
    sidebarDropdown.innerHTML = `
        <button class="dropdown-item" id="settingsBtn" type="button" role="menuitem">
            <span class="ph-icon ph-gear" aria-hidden="true"></span>
            Settings
        </button>
        <a href="/privacy" class="dropdown-item" role="menuitem">
            <span class="ph-icon ph-shield" aria-hidden="true"></span>
            Privacy
        </a>
        ${currentUser.is_admin ? `
        <a href="/admin" class="dropdown-item" id="adminLink" role="menuitem">
            <span class="ph-icon ph-shield" aria-hidden="true"></span>
            Admin
        </a>` : ''}
        <div class="dropdown-divider"></div>
        <a href="/auth/logout" class="dropdown-item dropdown-item-danger" role="menuitem">
            <span class="ph-icon ph-sign-out" aria-hidden="true"></span>
            Sign out
        </a>
    `;

    // Re-attach settings button listener
    const newSettingsBtn = document.getElementById('settingsBtn');
    if (newSettingsBtn) {
        newSettingsBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            sidebarDropdown.classList.add('hidden');
            showSettings();
        });
    }

    // Hide login prompt if shown
    hideLoginPrompt();
}

/**
 * @description Configures the sidebar UI for unauthenticated visitors. Shows a right-arrow
 *              icon in the avatar area and a "Sign In" link in the dropdown.
 * @returns {void}
 */
function showLoggedOutState() {
    // Update avatar to show login icon
    sidebarUserAvatar.replaceChildren();
    sidebarUserAvatar.classList.add('ph-icon', 'ph-arrow-right');
    sidebarUserAvatar.style.fontSize = '1rem';
    sidebarUserName.textContent = 'Sign in';

    // Update dropdown to show login option
    sidebarDropdown.innerHTML = `
        <a href="/auth/login" class="dropdown-item" role="menuitem">
            <span class="ph-icon ph-arrow-right" aria-hidden="true"></span>
            Sign in
        </a>
        <a href="/privacy" class="dropdown-item" role="menuitem">
            <span class="ph-icon ph-shield" aria-hidden="true"></span>
            Privacy
        </a>
    `;
}

/** @type {string} sessionStorage key for preserving a user's in-flight prompt across the login redirect */
const PENDING_DRAFT_KEY = 'pendingPromptDraft';

/**
 * @description Saves a user's prompt to sessionStorage so it can be restored after the
 *              OAuth login round-trip. sessionStorage is per-tab and survives the
 *              redirect to WorkOS and back, but is cleared when the tab closes.
 * @param {string} message - The user's prompt text
 * @returns {void}
 */
function savePendingDraft(message) {
    const trimmed = (message || '').trim();
    if (!trimmed) return;
    sessionStorage.setItem(PENDING_DRAFT_KEY, trimmed);
}

/**
 * @description Retrieves a previously saved prompt draft, if any.
 * @returns {string|null} The saved prompt, or null if none exists
 */
function getPendingDraft() {
    return sessionStorage.getItem(PENDING_DRAFT_KEY);
}

/**
 * @description Clears the saved prompt draft from sessionStorage.
 * @returns {void}
 */
function clearPendingDraft() {
    sessionStorage.removeItem(PENDING_DRAFT_KEY);
}

/**
 * @description Restores a pending prompt draft (saved before a login redirect) into the
 *              welcome-screen input so the user doesn't lose their message after signing in.
 *              Also focuses the input so the user can send immediately.
 * @returns {void}
 */
function restorePendingDraft() {
    const draft = getPendingDraft();
    if (!draft) return;
    clearPendingDraft();

    messageInput.value = draft;
    handleTextareaInput(messageInput, sendBtn);
    messageInput.focus();
    showToast('Your message is ready to send.');
}

/** @type {Window|null} Handle to the currently open login popup, if any */
let authPopup = null;

/**
 * @description Opens the WorkOS sign-in flow in a popup window so the main page does
 *              not reload. The popup navigates through /auth/login?popup=1 → WorkOS →
 *              /auth/callback, which sets the session cookie and posts a
 *              'rebbe-auth-complete' message back before closing itself. If the browser
 *              blocks the popup, falls back to a full redirect that relies on the
 *              sessionStorage draft being restored on reload.
 * @returns {void}
 */
function openLoginPopup() {
    const width = 500;
    const height = 700;
    // Center the popup on the user's screen
    const left = window.screenX + (window.outerWidth - width) / 2;
    const top = window.screenY + (window.outerHeight - height) / 2;
    const features = `width=${width},height=${height},left=${left},top=${top},resizable=yes,scrollbars=yes`;

    authPopup = window.open('/auth/login?popup=1', 'rebbeAuth', features);

    if (!authPopup) {
        // Popup blocked - fall back to full-page redirect. The draft is
        // already saved to sessionStorage and will be restored on reload.
        window.location.href = '/auth/login';
    }
}

/**
 * @description Handles a 'rebbe-auth-complete' postMessage from the login popup.
 *              Re-checks the session, hides the login prompt, refreshes the UI, and
 *              restores the user's saved draft back into the input.
 * @returns {Promise<void>}
 * @async
 */
async function handleAuthComplete() {
    // Verify sign-in actually succeeded (the cookie should be present now)
    const isAuthenticated = await checkAuth();
    if (!isAuthenticated) return;

    hideLoginPrompt();

    // Pick up any state that's only available post-login
    restorePendingDraft();
    loadConversations().catch(() => { /* non-fatal */ });
}

// Accept the auth-complete signal from the popup. Reject messages from foreign
// origins so a malicious embed can't forge authentication.
window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin) return;
    if (!event.data || event.data.type !== 'rebbe-auth-complete') return;
    handleAuthComplete();
});

/**
 * @description Displays a login prompt banner at the bottom of the viewport. Creates the
 *              element on first call, then toggles visibility on subsequent calls. The
 *              Sign In button opens a popup so the user's typed prompt is preserved in
 *              place without a page reload.
 * @returns {void}
 */
function showLoginPrompt() {
    let prompt = document.getElementById('loginPrompt');
    const hasDraft = !!getPendingDraft();
    const message = hasDraft
        ? 'Sign in to send your message'
        : 'Please sign in to chat with rebbe.dev';

    if (!prompt) {
        prompt = document.createElement('div');
        prompt.id = 'loginPrompt';
        prompt.className = 'login-prompt';
        document.body.appendChild(prompt);
    }

    prompt.innerHTML = `
        <div class="login-prompt-content">
            <p></p>
            <button class="login-prompt-btn" id="loginPromptSignInBtn">Sign In</button>
            <button class="login-prompt-close" id="loginPromptCloseBtn" type="button" aria-label="Close sign-in prompt">
                <span class="ph-icon ph-x" aria-hidden="true"></span>
            </button>
        </div>
    `;
    // Use textContent for the message to avoid any HTML injection risk
    prompt.querySelector('p').textContent = message;
    prompt.querySelector('#loginPromptSignInBtn').addEventListener('click', openLoginPopup);
    prompt.querySelector('#loginPromptCloseBtn').addEventListener('click', hideLoginPrompt);
    prompt.classList.add('visible');
}

/**
 * @description Hides the login prompt banner if it exists in the DOM.
 * @returns {void}
 */
function hideLoginPrompt() {
    const prompt = document.getElementById('loginPrompt');
    if (prompt) {
        prompt.classList.remove('visible');
    }
}

/**
 * @description Derives a one- or two-character initials string from the user's name or email.
 *              Falls back to '?' if no identifying information is available.
 * @param {string} firstName - The user's first name
 * @param {string} lastName - The user's last name
 * @param {string} email - The user's email address
 * @returns {string} Uppercase initials (1-2 characters)
 */
function getInitials(firstName, lastName, email) {
    if (firstName && lastName) {
        return (firstName[0] + lastName[0]).toUpperCase();
    } else if (firstName) {
        return firstName[0].toUpperCase();
    } else if (email) {
        return email[0].toUpperCase();
    }
    return '?';
}

/**
 * @description Briefly fades out an element's text, swaps its textContent, then fades it
 *              back in, using the shared --transition-fast token instead of an instant
 *              swap. Used for small pieces of UI chrome (credits balance, sidebar user
 *              name/avatar) whose values can change after the initial page load.
 * @param {HTMLElement} el - The element whose text should be updated
 * @param {string} newText - The new text content to display
 * @returns {void}
 */
function updateTextWithFade(el, newText) {
    if (!el) return;
    if (el.textContent === newText) return; // No visible change, skip the animation

    el.classList.add('text-fade-out');
    setTimeout(() => {
        el.textContent = newText;
        el.classList.remove('text-fade-out');
    }, 150);
}

/* ============================================================
 * EVENT LISTENERS
 * Central registration of all DOM event listeners. Called once
 * during initialization to wire up the entire UI.
 * ============================================================ */

/**
 * @description Registers all DOM event listeners for the application. Covers welcome screen
 *              input, chat input, sidebar controls, navigation, payment modal, settings,
 *              D'var Torah, profile form, suggestion chips, and textarea auto-resize.
 * @returns {void}
 */
function setupEventListeners() {
    // Welcome screen input
    messageInput.addEventListener('keydown', handleWelcomeKeydown);
    messageInput.addEventListener('input', () => handleTextareaInput(messageInput, sendBtn));
    sendBtn.addEventListener('click', () => sendFromWelcome());

    // Chat screen input
    chatInput.addEventListener('keydown', handleChatKeydown);
    chatInput.addEventListener('input', () => handleTextareaInput(chatInput, chatSendBtn));
    chatSendBtn.addEventListener('click', () => sendFromChat());

    // Sidebar toggle
    sidebarToggle.addEventListener('click', () => {
        if (window.innerWidth <= 820) closeSidebarMobile();
        else toggleSidebar();
    });
    menuBtn.addEventListener('click', toggleSidebarMobile);
    welcomeMenuBtn.addEventListener('click', toggleSidebarMobile);
    sidebarOverlay.addEventListener('click', closeSidebarMobile);

    // New chat button
    newChatBtn.addEventListener('click', startNewConversation);

    // Conversation list - single delegated listener handles item clicks, menu
    // button toggles, and delete button clicks for all rows, including rows
    // added by future re-renders (see handleConversationsListClick).
    conversationsList.addEventListener('click', handleConversationsListClick);

    // User menu in sidebar - entire profile area is clickable.
    // The dropdown is positioned absolutely above the profile element using
    // bounding rect calculations to work correctly regardless of sidebar state.
    userProfile.addEventListener('click', (e) => {
        e.stopPropagation();
        const rect = userProfile.getBoundingClientRect();
        sidebarDropdown.style.top = 'auto';
        sidebarDropdown.style.bottom = `${window.innerHeight - rect.top + 8}px`;
        sidebarDropdown.style.left = `${rect.left}px`;
        sidebarDropdown.classList.toggle('hidden');
        userProfile.setAttribute('aria-expanded', String(!sidebarDropdown.classList.contains('hidden')));
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', () => {
        sidebarDropdown.classList.add('hidden');
        userProfile.setAttribute('aria-expanded', 'false');
        document.querySelectorAll('.conversation-dropdown').forEach(d => d.classList.add('hidden'));
    });

    // Settings button
    settingsBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        sidebarDropdown.classList.add('hidden');
        showSettings();
    });

    // Payment modal listeners
    setupPaymentListeners();

    // Settings back button
    settingsBackBtn.addEventListener('click', hideSettings);

    // D'var Torah
    dvarTorahExpandBtn.addEventListener('click', showDvarTorah);
    dvarTorahBackBtn.addEventListener('click', hideDvarTorah);

    // Profile form listeners
    bioInput.addEventListener('input', updateBioCharCount);
    saveProfileBtn.addEventListener('click', saveProfile);
    languageDefaultSelect?.addEventListener('change', saveAccountLanguage);

    // Suggestion chips
    suggestionChips.forEach(chip => {
        chip.addEventListener('click', () => {
            const prompt = chip.dataset.prompt;
            messageInput.value = prompt;
            handleTextareaInput(messageInput, sendBtn);
            messageInput.focus();
        });
    });

    // Auto-resize textareas
    [messageInput, chatInput].forEach(textarea => {
        textarea.addEventListener('input', () => autoResize(textarea));
    });

    // Respect a reader who has moved away from the newest message.
    chatMessages.addEventListener('scroll', () => {
        shouldAutoScroll = isChatNearBottom();
    }, { passive: true });

    window.addEventListener('resize', () => {
        if (window.innerWidth > 820) closeSidebarMobile();
    });
}

/* ============================================================
 * SIDEBAR & NAVIGATION
 * Functions controlling sidebar collapse/expand behavior on
 * desktop and mobile, and screen-switching helpers.
 * ============================================================ */

/**
 * @description Toggles the sidebar between collapsed and expanded states on desktop.
 * @returns {void}
 */
function toggleSidebar() {
    sidebar.classList.toggle('collapsed');
    const expanded = !sidebar.classList.contains('collapsed');
    sidebarToggle.setAttribute('aria-expanded', String(expanded));
    sidebarToggle.setAttribute('aria-label', expanded ? 'Collapse conversation rail' : 'Expand conversation rail');
}

/**
 * @description Toggles sidebar visibility with responsive behavior. On mobile (<=768px),
 *              uses an overlay slide-in pattern. On desktop, toggles the collapsed state.
 * @returns {void}
 */
function toggleSidebarMobile() {
    // On mobile, use open/overlay behavior
    // On desktop with collapsed sidebar, toggle collapsed state
    const isMobile = window.innerWidth <= 820;

    if (isMobile) {
        setSidebarMobileOpen(!sidebar.classList.contains('open'));
    } else {
        // Desktop: toggle collapsed state
        sidebar.classList.toggle('collapsed');
    }
}

/**
 * @description Closes the mobile sidebar overlay by removing the 'open' and 'visible' classes.
 * @returns {void}
 */
function closeSidebarMobile() {
    setSidebarMobileOpen(false);
}

/**
 * Keeps the mobile rail, overlay, accessibility state, and page scroll in sync.
 * @param {boolean} open
 * @returns {void}
 */
function setSidebarMobileOpen(open) {
    sidebar.classList.toggle('open', open);
    sidebarOverlay.classList.toggle('visible', open);
    sidebarOverlay.classList.toggle('hidden', !open);
    sidebarOverlay.setAttribute('aria-hidden', String(!open));
    menuBtn.setAttribute('aria-expanded', String(open));
    welcomeMenuBtn.setAttribute('aria-expanded', String(open));
}

/**
 * @description Handles keydown events on the welcome screen textarea. Submits the message
 *              on Enter (without Shift) and allows Shift+Enter for newlines.
 * @param {KeyboardEvent} e - The keydown event
 * @returns {void}
 */
function handleWelcomeKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendFromWelcome();
    }
}

/**
 * @description Handles keydown events on the chat screen textarea. Same Enter/Shift+Enter
 *              behavior as the welcome screen handler.
 * @param {KeyboardEvent} e - The keydown event
 * @returns {void}
 */
function handleChatKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendFromChat();
    }
}

/**
 * @description Enables/disables the associated send button based on whether the textarea
 *              has non-whitespace content, and triggers auto-resize.
 * @param {HTMLTextAreaElement} textarea - The input textarea element
 * @param {HTMLButtonElement} button - The send button to enable/disable
 * @returns {void}
 */
function handleTextareaInput(textarea, button) {
    const hasContent = textarea.value.trim().length > 0;
    button.disabled = !hasContent;
    autoResize(textarea);
}

/**
 * @description Auto-resizes a textarea to fit its content up to a maximum height.
 *              Uses different max heights for the welcome input (200px) vs chat input (150px).
 * @param {HTMLTextAreaElement} textarea - The textarea element to resize
 * @returns {void}
 */
function autoResize(textarea) {
    textarea.style.height = 'auto';
    const maxHeight = textarea === messageInput ? 200 : 150;
    textarea.style.height = Math.min(textarea.scrollHeight, maxHeight) + 'px';
}

/**
 * @description Fetches the greeting message from the API. Currently hardcodes the display
 *              text to "Shalom, how can I help?" regardless of the server response.
 * @returns {Promise<void>}
 * @async
 */
async function loadGreeting() {
    try {
        const response = await fetch(`${API_BASE}/greeting`);
        if (response.ok) {
            const data = await response.json();
            greetingText.textContent = 'Shalom, how can I help?';
        }
    } catch (error) {
        console.error('Failed to load greeting:', error);
        greetingText.textContent = 'Shalom, how can I help?';
    } finally {
        // Reveal the greeting text and hide its skeleton placeholder now that
        // the fetch has settled (success or failure both resolve to the same
        // fallback text, so this always ends with the greeting visible).
        greetingText.classList.remove('hidden');
        if (greetingSkeleton) greetingSkeleton.classList.add('hidden');
    }
}

/* ============================================================
 * D'VAR TORAH
 * Weekly Torah portion display. Fetches the current parsha's
 * D'var Torah from the API and renders it in a dedicated screen.
 * ============================================================ */

/**
 * @description Fetches the weekly D'var Torah (Torah portion commentary) from the API.
 *              If the data is available and it is not a holiday week, caches the response
 *              and reveals the D'var Torah preview section on the welcome screen.
 * @param {boolean} [fresh=false] - Bypass the HTTP cache (used after a new
 *              sponsorship so the dedication appears without waiting out the
 *              endpoint's Cache-Control window)
 * @returns {Promise<void>}
 * @async
 */
async function loadDvarTorah(fresh = false) {
    try {
        const response = await fetch(`${API_BASE}/dvar-torah`, fresh ? { cache: 'no-store' } : undefined);
        if (!response.ok) return;

        const data = await response.json();
        if (data.is_holiday_week || !data.content) return;

        dvarTorahData = data;
        dvarTorahParsha.textContent = `${data.parsha_name} / ${data.parsha_name_hebrew}`;
        dvarTorahPreview.textContent = data.content.substring(0, 200) + '...';
        dvarTorahSection.classList.remove('hidden');
    } catch (error) {
        console.error('Failed to load d\'var Torah:', error);
    } finally {
        // Hide the skeleton placeholder once the fetch settles, regardless of
        // whether the preview card ended up being shown (e.g. holiday weeks
        // intentionally have no d'var Torah card).
        if (dvarTorahSkeleton) dvarTorahSkeleton.classList.add('hidden');
    }
}

/**
 * @description Navigates to the full-screen D'var Torah view. Hides all other screens,
 *              sets the title to the parsha name, and converts the plain-text content
 *              into HTML paragraphs (splitting on double newlines).
 * @returns {void}
 */
function showDvarTorah() {
    if (!dvarTorahData) return;

    welcomeScreen.classList.add('hidden');
    chatScreen.classList.add('hidden');
    settingsScreen.classList.add('hidden');
    dvarTorahScreen.classList.remove('hidden');

    dvarTorahScreenTitle.textContent = `Parashat ${dvarTorahData.parsha_name}`;

    // Sponsor dedications for this parsha week (shown above the teaching,
    // in the tradition of dedicating Torah learning)
    let sponsorsHtml = '';
    if (dvarTorahData.sponsors && dvarTorahData.sponsors.length) {
        const lines = dvarTorahData.sponsors
            .map(s => `<p class="dvar-sponsor-line" dir="auto">${escapeHtml(formatDedication(s))}</p>`)
            .join('');
        sponsorsHtml = `<div class="dvar-sponsors">${lines}</div>`;
    }

    // Convert plain text to paragraphs (escaped - content is server-generated
    // but rendered consistently with the chat path)
    const paragraphs = dvarTorahData.content.split('\n\n').filter(p => p.trim());
    const html = paragraphs.map(p => …14379 tokens truncated…Copy(content) {
    try {
        await navigator.clipboard.writeText(content);
        showToast('Copied to clipboard');
    } catch (error) {
        console.error('Failed to copy:', error);
        showToast('Failed to copy');
    }
}

/**
 * @description Streams text-to-speech audio from the /api/speak endpoint and plays it
 *              using the Web Audio API. The audio format is raw PCM: 24kHz sample rate,
 *              16-bit signed integer, mono (little-endian). This matches the ElevenLabs
 *              streaming output format.
 *
 *              Playback uses a chain of AudioBufferSourceNodes scheduled back-to-back.
 *              Each chunk of PCM bytes received from the ReadableStream is:
 *              1. Combined with any leftover bytes from the previous chunk (PCM 16-bit
 *                 requires an even number of bytes)
 *              2. Converted from Int16 to Float32 by dividing by 32768
 *              3. Wrapped in an AudioBuffer at 24kHz sample rate
 *              4. Scheduled via AudioBufferSourceNode.start(nextStartTime)
 *
 *              The activeSources array tracks all scheduled nodes so they can be
 *              immediately stopped if the user clicks the button again (toggle stop).
 *
 * @param {string} content - The message text to convert to speech
 * @param {HTMLButtonElement} button - The speak button element (toggled between loading/playing states)
 * @returns {Promise<void>}
 * @async
 */
async function handleSpeak(content, button) {
    // Initialize AudioContext on first use - must happen inside a user gesture handler
    // to satisfy the browser autoplay policy. Sample rate is set to 24kHz to match
    // the ElevenLabs PCM output format, avoiding any resampling.
    if (!audioContext) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        audioContext = new AudioContextClass({ sampleRate: 24000 });
    }

    // Resume AudioContext immediately - this satisfies autoplay policy
    if (audioContext.state === 'suspended') {
        await audioContext.resume();
    }

    // Get message ID for tracking (from parent message element)
    const messageEl = button.closest('.message');
    const messageId = messageEl ? messageEl.dataset.messageId : null;
    const textLength = content ? content.length : 0;

    // If already playing, stop all scheduled AudioBufferSourceNodes immediately
    if (isPlaying) {
        stopRequested = true;
        for (const source of activeSources) {
            try {
                source.stop();
            } catch (e) {
                // Ignore errors from sources that have already finished playing
            }
        }
        activeSources = [];
        button.classList.remove('playing');
        isPlaying = false;
        trackTTSEvent('stop', messageId);
        return;
    }

    button.classList.add('loading');
    isPlaying = true;
    stopRequested = false;
    const ttsStartTime = Date.now();

    // Track TTS start
    trackTTSEvent('start', messageId, textLength);

    /** @type {number} PCM sample rate matching ElevenLabs output (24kHz, 16-bit signed, mono) */
    const PCM_SAMPLE_RATE = 24000;

    try {
        const response = await fetch(`${API_BASE}/speak`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: content })
        });

        if (!response.ok) {
            const errorText = await response.text();
            console.error('Speak API error:', response.status, errorText);
            throw new Error('Speech generation failed');
        }

        // Stream the PCM response using a ReadableStream reader.
        // nextStartTime tracks when the next AudioBuffer should begin playing,
        // ensuring gapless back-to-back scheduling of audio chunks.
        const reader = response.body.getReader();
        let nextStartTime = audioContext.currentTime;
        let firstChunk = true;
        let lastSource = null;
        let leftoverBytes = new Uint8Array(0); // Holds odd trailing byte from previous chunk

        while (true) {
            if (stopRequested) {
                await reader.cancel();
                break;
            }

            const { done, value } = await reader.read();
            if (done) break;

            // Combine leftover bytes from the previous iteration with the new chunk.
            // PCM 16-bit requires an even number of bytes (2 bytes per sample), so
            // any trailing odd byte is saved for the next iteration.
            const combined = new Uint8Array(leftoverBytes.length + value.length);
            combined.set(leftoverBytes);
            combined.set(value, leftoverBytes.length);

            const usableLength = combined.length - (combined.length % 2);
            leftoverBytes = combined.slice(usableLength);
            const pcmData = combined.slice(0, usableLength);

            if (pcmData.length === 0) continue;

            // Convert Int16 PCM to Float32 for the Web Audio API.
            // DataView with little-endian flag ensures correct byte order regardless
            // of the host system's endianness. The division by 32768 normalizes
            // the signed 16-bit range [-32768, 32767] to the Float32 range [-1.0, 1.0].
            const numSamples = pcmData.length / 2;
            const float32 = new Float32Array(numSamples);
            const dataView = new DataView(pcmData.buffer, pcmData.byteOffset, pcmData.byteLength);
            for (let i = 0; i < numSamples; i++) {
                const int16Value = dataView.getInt16(i * 2, true);
                float32[i] = int16Value / 32768;
            }

            // Create a mono AudioBuffer at the PCM sample rate and fill channel 0
            const audioBuffer = audioContext.createBuffer(1, float32.length, PCM_SAMPLE_RATE);
            audioBuffer.getChannelData(0).set(float32);

            // Create an AudioBufferSourceNode, connect it to the default output,
            // and schedule it to play immediately after the previous chunk ends.
            const source = audioContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(audioContext.destination);

            // Track all scheduled sources so they can be stopped on user request
            activeSources.push(source);

            // Schedule gapless playback: use whichever is later - the planned
            // nextStartTime or the current audio clock (handles scheduling drift)
            const startTime = Math.max(nextStartTime, audioContext.currentTime);
            source.start(startTime);
            nextStartTime = startTime + audioBuffer.duration;
            lastSource = source;

            // Update UI on first chunk
            if (firstChunk) {
                button.classList.remove('loading');
                button.classList.add('playing');
                firstChunk = false;
            }
        }

        // Attach an onended callback to the last scheduled source to clean up
        // playback state and track completion analytics when audio finishes naturally.
        if (lastSource && !stopRequested) {
            lastSource.onended = () => {
                button.classList.remove('playing');
                isPlaying = false;
                activeSources = [];
                // Track completion with duration
                const durationMs = Date.now() - ttsStartTime;
                trackTTSEvent('complete', messageId, textLength, durationMs);
            };
        } else {
            button.classList.remove('playing', 'loading');
            isPlaying = false;
            activeSources = [];
        }

    } catch (error) {
        // Handles network failures, non-OK HTTP responses, and stream read errors.
        // Resets all playback state and notifies the user via toast.
        console.error('Speech generation failed:', error);
        button.classList.remove('loading', 'playing');
        isPlaying = false;
        activeSources = [];
        showToast('Could not generate speech');
        trackTTSEvent('error', messageId, textLength, null, error.message || 'Unknown error');
    }
}

/**
 * @description Submits or removes user feedback (thumbs up/down) for a message.
 *              Toggling the same button removes the feedback; clicking the opposite
 *              button switches the feedback type. Only one feedback type can be active
 *              per message at a time.
 * @param {string|null} messageId - Server-assigned message ID
 * @param {string} feedbackType - Either 'thumbs_up' or 'thumbs_down'
 * @param {HTMLButtonElement} button - The clicked feedback button
 * @param {HTMLElement} actionsDiv - Parent container for clearing the opposite button's active state
 * @returns {Promise<void>}
 * @async
 */
async function handleFeedback(messageId, feedbackType, button, actionsDiv) {
    if (!messageId) {
        showToast('Cannot save feedback');
        return;
    }

    const isActive = button.classList.contains('active');

    try {
        if (isActive) {
            // Remove feedback
            await fetch(`${API_BASE}/feedback/${messageId}`, { method: 'DELETE' });
            button.classList.remove('active');
        } else {
            // Clear opposite button if active
            actionsDiv.querySelectorAll('.action-btn.active').forEach(b => b.classList.remove('active'));

            // Submit feedback
            await fetch(`${API_BASE}/feedback`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message_id: messageId, feedback_type: feedbackType })
            });
            button.classList.add('active');
        }
    } catch (error) {
        // Network or server error when saving feedback - notify user but don't disrupt UX
        console.error('Failed to save feedback:', error);
        showToast('Could not save feedback');
    }
}

/**
 * @description Displays a temporary toast notification at the bottom of the viewport.
 *              Removes any existing toast before creating a new one. Uses requestAnimationFrame
 *              for the entrance animation and auto-hides after 2 seconds with a 300ms exit transition.
 * @param {string} message - The text to display in the toast
 * @returns {void}
 */
function showToast(message) {
    // Remove existing toast
    const existingToast = document.querySelector('.toast');
    if (existingToast) {
        existingToast.remove();
    }

    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    document.body.appendChild(toast);

    // Trigger animation
    requestAnimationFrame(() => {
        toast.classList.add('visible');
    });

    // Auto-hide
    setTimeout(() => {
        toast.classList.remove('visible');
        setTimeout(() => toast.remove(), 300);
    }, 2000);
}

/* ============================================================
 * STRIPE PAYMENTS
 * Credit purchase flow using Stripe Elements. The flow is:
 * 1. User opens modal and selects a package (10 or 25 credits)
 * 2. A PaymentIntent + CustomerSession are created server-side
 * 3. Stripe Elements mounts a PaymentElement in the modal
 * 4. On submit, stripe.confirmPayment() handles 3DS/redirects
 * 5. Fulfillment uses a dual path: webhooks (production) or
 *    client-side verify-and-fulfill (development/staging)
 * ============================================================ */

let activeModal = null;
let modalReturnFocus = null;

/** @param {HTMLElement} modal */
function activateModal(modal) {
    modalReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    activeModal = modal;
    modal.setAttribute('aria-hidden', 'false');
    document.addEventListener('keydown', handleModalKeydown);
    requestAnimationFrame(() => {
        const first = getModalFocusables(modal)[0];
        (first || modal).focus();
    });
}

/** @param {HTMLElement} modal */
function deactivateModal(modal) {
    modal.setAttribute('aria-hidden', 'true');
    if (activeModal === modal) {
        activeModal = null;
        document.removeEventListener('keydown', handleModalKeydown);
        if (modalReturnFocus && document.contains(modalReturnFocus)) modalReturnFocus.focus();
        modalReturnFocus = null;
    }
}

/** @param {HTMLElement} modal @returns {HTMLElement[]} */
function getModalFocusables(modal) {
    return Array.from(modal.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'))
        .filter(element => element.offsetParent !== null);
}

/** @param {KeyboardEvent} event */
function handleModalKeydown(event) {
    if (!activeModal) return;
    if (event.key === 'Escape') {
        event.preventDefault();
        if (activeModal === purchaseModal) closePurchaseModalHandler();
        else closeSponsorModalHandler();
        return;
    }
    if (event.key !== 'Tab') return;
    const focusables = getModalFocusables(activeModal);
    if (!focusables.length) {
        event.preventDefault();
        activeModal.focus();
        return;
    }
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
}

/** Safely renders an inline provider or network error. */
function renderPaymentLoadError(container, message) {
    container.replaceChildren();
    const error = document.createElement('p');
    error.className = 'payment-error-text';
    error.setAttribute('role', 'alert');
    error.textContent = message || 'Failed to load payment form. Please try again.';
    container.appendChild(error);
}

/**
 * @description Builds the Stripe Elements appearance for the theme currently resolved
 *              on the document. theme.js always writes a concrete 'light' or 'dark' to
 *              data-theme (it resolves the 'system' preference itself), so this never
 *              has to consult matchMedia.
 * @returns {Object} A Stripe Elements appearance object.
 */
function stripeAppearance() {
    const dark = document.documentElement.dataset.theme === 'dark';
    return {
        theme: dark ? 'night' : 'stripe',
        variables: {
            colorPrimary: dark ? '#86a8e3' : '#315da8',
            colorBackground: dark ? '#161f2c' : '#fafcfe',
            colorText: dark ? '#eff4fa' : '#122033',
            colorDanger: dark ? '#f08b8b' : '#b23a3a',
            fontFamily: 'Hanken Grotesk, Arial, sans-serif',
            borderRadius: '8px',
            spacingUnit: '4px',
        }
    };
}

/**
 * @description Repaints any mounted Stripe Elements when the theme changes. Elements
 *              renders inside a cross-origin iframe, so it cannot inherit the page's
 *              CSS variables -- without this, toggling the theme with a payment modal
 *              open leaves the card form in the previous theme.
 * @returns {void}
 */
function syncStripeAppearance() {
    const appearance = stripeAppearance();
    [elements, sponsorElements].forEach(instance => {
        if (!instance) return;
        try {
            instance.update({ appearance });
        } catch (error) {
            // A stale Elements group (modal already closed, intent superseded)
            // rejects updates. The next mount picks up the current theme anyway.
            console.debug('Stripe appearance update skipped:', error);
        }
    });
}

window.addEventListener('rebbe-theme-change', syncStripeAppearance);

/**
 * @description Updates the "Pay Now" button's label and spinner visibility. Centralizes
 *              the text/spinner swap so every stage of the payment flow (processing,
 *              adding credits, error recovery) stays visually consistent.
 * @param {string} text - The label to display inside the button
 * @param {boolean} [showSpinner=false] - Whether to show the inline loading spinner
 * @returns {void}
 */
function setPurchaseButtonState(text, showSpinner = false) {
    if (!submitPayment) return;
    const btnText = submitPayment.querySelector('.btn-text');
    const spinner = submitPayment.querySelector('.purchase-spinner');
    if (btnText) btnText.textContent = text;
    if (spinner) spinner.classList.toggle('hidden', !showSpinner);
}

/**
 * @description Registers click handlers for the payment modal: open/close buttons,
 *              backdrop click to close, package card selection, and payment submit.
 * @returns {void}
 */
function setupPaymentListeners() {
    if (buyCreditsBtn) {
        buyCreditsBtn.addEventListener('click', openPurchaseModal);
    }
    if (closePurchaseModal) {
        closePurchaseModal.addEventListener('click', closePurchaseModalHandler);
    }
    if (purchaseModal) {
        purchaseModal.addEventListener('click', (e) => {
            if (e.target === purchaseModal) closePurchaseModalHandler();
        });
    }

    packageCards.forEach(card => {
        card.addEventListener('click', () => selectPackage(card.dataset.package));
    });

    if (submitPayment) {
        submitPayment.addEventListener('click', handlePaymentSubmit);
    }
}

/**
 * @description Opens the credit purchase modal. Resets the modal to its initial state,
 *              lazily loads Stripe.js if not already loaded, and initializes the payment form.
 * @returns {Promise<void>}
 * @async
 */
async function openPurchaseModal() {
    if (!purchaseModal) return;

    // Reset modal state
    resetModalState();

    purchaseModal.classList.remove('hidden');
    purchaseModal.classList.add('visible');
    activateModal(purchaseModal);

    // Load Stripe.js if not already loaded
    if (!stripe) {
        await loadStripeJs();
    }

    // Create payment intent and mount form
    await initializePaymentForm();
}

/**
 * @description Closes the purchase modal with an animation. Destroys the Stripe
 *              PaymentElement to prevent memory leaks and resets the modal state
 *              after the CSS transition completes (300ms).
 * @returns {void}
 */
function closePurchaseModalHandler() {
    if (!purchaseModal) return;

    purchaseModal.classList.remove('visible');
    purchaseModal.classList.add('hidden');
    deactivateModal(purchaseModal);

    // Clean up payment element
    if (paymentElement) {
        paymentElement.destroy();
        paymentElement = null;
    }
    elements = null;

    // Reset modal state after animation
    setTimeout(resetModalState, 300);
}

/**
 * @description Resets all payment modal UI elements to their initial state: shows the
 *              package selection and loading placeholder, hides status messages, resets
 *              the submit button, and selects the default 10-credit package.
 * @returns {void}
 */
function resetModalState() {
    // Show package selection and footer
    if (packageSelection) packageSelection.classList.remove('hidden');
    if (modalFooter) modalFooter.classList.remove('hidden');
    if (paymentElementContainer) {
        paymentElementContainer.classList.remove('hidden');
        paymentElementContainer.innerHTML = '<div class="payment-loading">Loading payment form...</div>';
    }

    // Hide status messages
    if (paymentStatus) paymentStatus.classList.add('hidden');
    if (paymentSuccess) paymentSuccess.classList.add('hidden');
    if (paymentError) paymentError.classList.add('hidden');

    // Reset button
    if (submitPayment) {
        submitPayment.disabled = true;
        setPurchaseButtonState('Pay Now', false);
    }

    // Reset package selection
    selectedPackage = 'credits_10';
    packageCards.forEach(card => {
        const selected = card.dataset.package === 'credits_10';
        card.classList.toggle('selected', selected);
        card.setAttribute('aria-pressed', String(selected));
    });
}

/**
 * @description Selects a credit package and reinitializes the Stripe payment form with
 *              the new package's price. Updates the visual selection state on all cards.
 * @param {string} packageId - Package identifier (e.g., 'credits_10', 'credits_25')
 * @returns {void}
 */
function selectPackage(packageId) {
    selectedPackage = packageId;
    packageCards.forEach(card => {
        const selected = card.dataset.package === packageId;
        card.classList.toggle('selected', selected);
        card.setAttribute('aria-pressed', String(selected));
    });

    // Reinitialize payment form with new package
    initializePaymentForm();
}

/**
 * @description Dynamically loads the Stripe.js library by injecting a script tag.
 *              Returns immediately if Stripe is already loaded. This is done lazily
 *              to avoid loading the ~40KB library until the user opens the purchase modal.
 * @returns {Promise<void>} Resolves when Stripe.js is loaded, rejects on script error
 */
function loadStripeJs() {
    return new Promise((resolve, reject) => {
        if (window.Stripe) {
            resolve();
            return;
        }
        const script = document.createElement('script');
        script.src = 'https://js.stripe.com/v3/';
        script.onload = resolve;
        script.onerror = () => reject(new Error('Failed to load Stripe.js'));
        document.head.appendChild(script);
    });
}

/**
 * @description Initializes the Stripe payment form by:
 *              1. Creating a PaymentIntent on the server for the selected package
 *              2. Receiving the client_secret, customer_session_client_secret, and publishable_key
 *              3. Initializing a Stripe Elements instance with the dark theme appearance
 *              4. Creating and mounting a PaymentElement (handles cards, wallets, etc.)
 *
 *              The CustomerSession client secret enables features like saved payment
 *              methods and Link autofill for returning customers.
 *
 * @returns {Promise<void>}
 * @async
 */
async function initializePaymentForm() {
    if (!paymentElementContainer || !submitPayment) return;

    submitPayment.disabled = true;
    paymentElementContainer.innerHTML = '<div class="payment-loading">Loading payment form...</div>';

    try {
        // Create payment intent
        const response = await fetch(`${API_BASE}/payments/create-intent`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ package_id: selectedPackage }),
            credentials: 'include'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create payment intent');
        }

        const { client_secret, customer_session_client_secret, publishable_key } = await response.json();

        // Initialize Stripe if needed
        if (!stripe) {
            stripe = Stripe(publishable_key);
        }

        // Create Elements with customer session
        elements = stripe.elements({
            clientSecret: client_secret,
            customerSessionClientSecret: customer_session_client_secret,
            appearance: stripeAppearance()
        });

        // Create and mount PaymentElement
        paymentElement = elements.create('payment');
        paymentElementContainer.innerHTML = '';
        paymentElement.mount(paymentElementContainer);

        paymentElement.on('ready', () => {
            submitPayment.disabled = false;
        });

        paymentElement.on('change', (event) => {
            submitPayment.disabled = !event.complete;
        });

    } catch (error) {
        // Handles PaymentIntent creation failures, Stripe initialization errors,
        // or network issues. Shows the error message inline in the payment container.
        console.error('Failed to initialize payment form:', error);
        renderPaymentLoadError(paymentElementContainer, error.message);
    }
}

/**
 * @description Handles the "Pay Now" button click. Calls stripe.confirmPayment() which
 *              may trigger 3DS authentication or redirect to an external payment method
 *              (e.g., Amazon Pay). Uses redirect: 'if_required' to stay on the page for
 *              simple card payments.
 *
 *              After successful payment, attempts dual fulfillment:
 *              - Primary (production): Stripe webhooks handle credit fulfillment server-side
 *              - Fallback (development): Client calls /payments/verify-and-fulfill to trigger
 *                immediate credit addition. If this endpoint returns 404, it means we are in
 *                production and webhooks will handle it.
 *
 *              All paths converge on showing a success message and refreshing the credit
 *              balance, even if the verify-and-fulfill call fails (since webhooks will
 *              eventually fulfill the order).
 *
 * @returns {Promise<void>}
 * @async
 */
async function handlePaymentSubmit() {
    if (!stripe || !elements || !submitPayment) return;

    submitPayment.disabled = true;
    setPurchaseButtonState('Processing...', true);

    try {
        const { error, paymentIntent } = await stripe.confirmPayment({
            elements,
            confirmParams: {
                return_url: window.location.origin + '/?payment=success',
            },
            redirect: 'if_required'
        });

        if (error) {
            showPaymentErrorMessage(error.message);
            submitPayment.disabled = false;
            setPurchaseButtonState('Pay Now', false);
        } else if (paymentIntent && paymentIntent.status === 'succeeded') {
            // Payment succeeded - try to verify and fulfill immediately (non-production only)
            setPurchaseButtonState('Adding credits...', true);

            // Attempt client-side verification and fulfillment. This is a non-production
            // convenience path; in production, Stripe webhooks handle fulfillment and
            // this endpoint returns 404.
            try {
                const verifyResponse = await fetch(`${API_BASE}/payments/verify-and-fulfill`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ payment_intent_id: paymentIntent.id }),
                    credentials: 'include'
                });

                if (verifyResponse.status === 404) {
                    // Endpoint disabled in production - webhooks will handle fulfillment
                    showPaymentSuccessMessage();
                    await loadCredits();
                    setTimeout(closePurchaseModalHandler, 2000);
                } else {
                    const result = await verifyResponse.json();

                    if (result.success) {
                        showPaymentSuccessMessage();
                        await loadCredits();
                        setTimeout(closePurchaseModalHandler, 2000);
                    } else {
                        // Payment succeeded but fulfillment failed - show partial success
                        console.error('Fulfillment issue:', result.message);
                        showPaymentSuccessMessage();
                        showToast('Payment received. Credits will be added shortly.');
                        await loadCredits();
                        setTimeout(closePurchaseModalHandler, 2000);
                    }
                }
            } catch (verifyError) {
                // Network error during verification. Payment already succeeded on Stripe's
                // side, so webhooks will fulfill the order. Show success to the user.
                console.error('Verification error:', verifyError);
                showPaymentSuccessMessage();
                showToast('Payment received. Credits will be added shortly.');
                await loadCredits();
                setTimeout(closePurchaseModalHandler, 2000);
            }
        } else {
            // Payment requires additional action or is processing
            showPaymentSuccessMessage();
            await loadCredits();
            setTimeout(closePurchaseModalHandler, 2000);
        }
    } catch (err) {
        // Catch-all for unexpected errors during the entire payment flow
        // (Stripe SDK errors, network issues, etc.)
        console.error('Payment error:', err);
        showPaymentErrorMessage('An unexpected error occurred.');
        submitPayment.disabled = false;
        setPurchaseButtonState('Pay Now', false);
    }
}

/**
 * @description Transitions the payment modal to the success state by hiding the form
 *              elements and showing the success message panel.
 * @returns {void}
 */
function showPaymentSuccessMessage() {
    if (packageSelection) packageSelection.classList.add('hidden');
    if (paymentElementContainer) paymentElementContainer.classList.add('hidden');
    if (modalFooter) modalFooter.classList.add('hidden');
    if (paymentStatus) paymentStatus.classList.remove('hidden');
    if (paymentSuccess) paymentSuccess.classList.remove('hidden');
    announce('Payment successful. Credits were added.');
}

/**
 * @description Shows a temporary error message in the payment modal. The error auto-hides
 *              after 5 seconds so the user can retry without manual dismissal.
 * @param {string} message - The error message to display
 * @returns {void}
 */
function showPaymentErrorMessage(message) {
    if (paymentErrorMessage) paymentErrorMessage.textContent = message;
    if (paymentError) {
        paymentError.classList.remove('hidden');
        setTimeout(() => {
            paymentError.classList.add('hidden');
        }, 5000);
    }
}

/* ============================================================
 * D'VAR TORAH SPONSORSHIP (TZEDAKAH)
 * Two-step Stripe flow for dedicating the week's d'var Torah:
 * 1. Pick a chai-multiple tier, choose a dedication type, and
 *    write the dedication text.
 * 2. Pay via a Stripe PaymentElement (same machinery as the
 *    credit purchase modal).
 * ============================================================ */

/** @type {string} Currently selected sponsorship tier ID */
let selectedSponsorTier = 'chai';
/** @type {object|null} Stripe Elements instance for the sponsorship modal */
let sponsorElements = null;
/** @type {object|null} Mounted PaymentElement for the sponsorship modal */
let sponsorPaymentElement = null;
/** @type {boolean} Whether the sponsor modal's static listeners are attached */
let sponsorModalWired = false;

/**
 * @description Opens the sponsorship modal at step 1 (tier + dedication),
 *              wiring its static event listeners on first open.
 * @returns {void}
 */
function openSponsorModal() {
    const modal = document.getElementById('sponsorModal');
    if (!modal) return;

    if (!sponsorModalWired) {
        wireSponsorModal();
        sponsorModalWired = true;
    }

    resetSponsorModalState();
    modal.classList.remove('hidden');
    modal.classList.add('visible');
    activateModal(modal);
}

/**
 * @description Attaches one-time event listeners for the sponsorship modal:
 *              close button, backdrop click, tier selection, and the two
 *              step-advancing buttons.
 * @returns {void}
 */
function wireSponsorModal() {
    const modal = document.getElementById('sponsorModal');

    document.getElementById('closeSponsorModal').addEventListener('click', closeSponsorModalHandler);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeSponsorModalHandler();
    });

    modal.querySelectorAll('.package-card[data-tier]').forEach(card => {
        card.addEventListener('click', () => {
            selectedSponsorTier = card.dataset.tier;
            modal.querySelectorAll('.package-card[data-tier]').forEach(c => {
                const selected = c.dataset.tier === selectedSponsorTier;
                c.classList.toggle('selected', selected);
                c.setAttribute('aria-pressed', String(selected));
            });
        });
    });

    document.getElementById('sponsorContinueBtn').addEventListener('click', startSponsorshipPayment);
    document.getElementById('submitSponsorship').addEventListener('click', handleSponsorshipSubmit);
}

/**
 * @description Resets the sponsorship modal to step 1 with the default tier selected.
 * @returns {void}
 */
function resetSponsorModalState() {
    const modal = document.getElementById('sponsorModal');
    document.getElementById('sponsorStepDetails').classList.remove('hidden');
    document.getElementById('sponsorStepPayment').classList.add('hidden');
    document.getElementById('sponsorStatus').classList.add('hidden');
    document.getElementById('sponsorSuccess').classList.add('hidden');
    document.getElementById('sponsorError').classList.add('hidden');
    document.getElementById('submitSponsorship').disabled = true;

    selectedSponsorTier = 'chai';
    modal.querySelectorAll('.package-card[data-tier]').forEach(c => {
        const selected = c.dataset.tier === 'chai';
        c.classList.toggle('selected', selected);
        c.setAttribute('aria-pressed', String(selected));
    });
}

/**
 * @description Closes the sponsorship modal and tears down the Stripe PaymentElement.
 * @returns {void}
 */
function closeSponsorModalHandler() {
    const modal = document.getElementById('sponsorModal');
    if (!modal) return;

    modal.classList.remove('visible');
    modal.classList.add('hidden');
    deactivateModal(modal);

    if (sponsorPaymentElement) {
        sponsorPaymentElement.destroy();
        sponsorPaymentElement = null;
    }
    sponsorElements = null;

    setTimeout(resetSponsorModalState, 300);
}

/**
 * @description Step 1 -> 2 transition: validates the dedication, creates the
 *              sponsorship PaymentIntent on the server, and mounts the Stripe
 *              PaymentElement.
 * @returns {Promise<void>}
 * @async
 */
async function startSponsorshipPayment() {
    const dedication = document.getElementById('sponsorDedication').value.trim();
    const dedicationType = document.getElementById('sponsorDedicationType').value;
    const errorEl = document.getElementById('sponsorDetailsError');

    if (dedication.length < 2) {
        errorEl.textContent = 'Please enter a dedication (e.g. a name).';
        errorEl.classList.remove('hidden');
        return;
    }
    errorEl.classList.add('hidden');

    const container = document.getElementById('sponsorPaymentElementContainer');
    document.getElementById('sponsorStepDetails').classList.add('hidden');
    document.getElementById('sponsorStepPayment').classList.remove('hidden');
    container.innerHTML = '<div class="payment-loading">Loading payment form...</div>';

    try {
        const response = await fetch(`${API_BASE}/payments/create-sponsorship-intent`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                tier_id: selectedSponsorTier,
                dedication: dedication,
                dedication_type: dedicationType,
            }),
            credentials: 'include',
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to start sponsorship');
        }

        const { client_secret, customer_session_client_secret, publishable_key } = await response.json();

        if (!window.Stripe) {
            await loadStripeJs();
        }
        if (!stripe) {
            stripe = Stripe(publishable_key);
        }

        sponsorElements = stripe.elements({
            clientSecret: client_secret,
            customerSessionClientSecret: customer_session_client_secret,
            appearance: stripeAppearance(),
        });

        sponsorPaymentElement = sponsorElements.create('payment');
        container.innerHTML = '';
        sponsorPaymentElement.mount(container);

        const submitBtn = document.getElementById('submitSponsorship');
        sponsorPaymentElement.on('ready', () => { submitBtn.disabled = false; });
        sponsorPaymentElement.on('change', (event) => { submitBtn.disabled = !event.complete; });

    } catch (error) {
        console.error('Failed to start sponsorship payment:', error);
        renderPaymentLoadError(container, error.message);
    }
}

/**
 * @description Confirms the sponsorship payment. On success, attempts the
 *              dev-only verify-and-fulfill path (production relies on
 *              webhooks), shows the success panel, and refreshes the d'var
 *              Torah data so the new dedication appears.
 * @returns {Promise<void>}
 * @async
 */
async function handleSponsorshipSubmit() {
    if (!stripe || !sponsorElements) return;

    const submitBtn = document.getElementById('submitSponsorship');
    submitBtn.disabled = true;

    try {
        const { error, paymentIntent } = await stripe.confirmPayment({
            elements: sponsorElements,
            confirmParams: {
                return_url: window.location.origin + '/?sponsorship=success',
            },
            redirect: 'if_required',
        });

        if (error) {
            showSponsorError(error.message);
            submitBtn.disabled = false;
            return;
        }

        if (paymentIntent && paymentIntent.status === 'succeeded') {
            // Dev-only immediate fulfillment; in production the webhook
            // completes the sponsorship (404 here is expected and fine).
            try {
                await fetch(`${API_BASE}/payments/verify-and-fulfill`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ payment_intent_id: paymentIntent.id }),
                    credentials: 'include',
                });
            } catch (verifyError) {
                console.error('Sponsorship verification error:', verifyError);
            }
        }

        document.getElementById('sponsorStepPayment').classList.add('hidden');
        document.getElementById('sponsorStatus').classList.remove('hidden');
        document.getElementById('sponsorSuccess').classList.remove('hidden');
        announce('Sponsorship completed successfully.');

        // Refresh so the dedication shows on the d'var Torah screen
        try {
            const refreshed = await fetch(`${API_BASE}/dvar-torah`);
            if (refreshed.ok) {
                const data = await refreshed.json();
                if (!data.is_holiday_week && data.content) {
                    dvarTorahData = data;
                }
            }
        } catch (refreshError) {
            console.error('Failed to refresh d\'var Torah:', refreshError);
        }

        setTimeout(() => {
            closeSponsorModalHandler();
            if (!dvarTorahScreen.classList.contains('hidden')) {
                showDvarTorah();
            }
        }, 2500);

    } catch (err) {
        console.error('Sponsorship payment error:', err);
        showSponsorError('An unexpected error occurred.');
        submitBtn.disabled = false;
    }
}

/**
 * @description Shows a temporary error message inside the sponsorship modal.
 * @param {string} message - The error message to display
 * @returns {void}
 */
function showSponsorError(message) {
    const errorEl = document.getElementById('sponsorError');
    const messageEl = document.getElementById('sponsorErrorMessage');
    if (messageEl) messageEl.textContent = message;
    if (errorEl) {
        errorEl.classList.remove('hidden');
        setTimeout(() => errorEl.classList.add('hidden'), 5000);
    }
}
