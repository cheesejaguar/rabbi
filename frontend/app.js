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
    const html = paragraphs.map(p => `<p dir="auto">${escapeHtml(p).replace(/\n/g, ' ')}</p>`).join('');

    const ctaHtml = `
        <div class="dvar-sponsor-cta">
            <button class="sponsor-btn" id="sponsorDvarBtn">Sponsor this week's d'var Torah</button>
            <p class="sponsor-hint">Dedicate this week's Torah learning in memory or in honor of a loved one.</p>
        </div>`;

    dvarTorahScreenContent.innerHTML = `${sponsorsHtml}<div class="dvar-torah-body">${html}</div>${ctaHtml}`;

    const sponsorBtn = document.getElementById('sponsorDvarBtn');
    if (sponsorBtn) {
        sponsorBtn.addEventListener('click', () => {
            if (!currentUser) {
                showLoginPrompt();
                return;
            }
            openSponsorModal();
        });
    }
}

/**
 * @description Formats a sponsorship dedication for display, prefixing the sponsor's
 *              text with traditional dedication language based on its type.
 * @param {{dedication: string, dedication_type: string}} s - A sponsorship record
 * @returns {string} The full dedication line
 */
function formatDedication(s) {
    const prefixes = {
        memory: 'In loving memory of',
        honor: 'In honor of',
        refuah: 'For a refuah shleima for',
        gratitude: 'In gratitude for',
        general: 'Dedicated by',
    };
    return `${prefixes[s.dedication_type] || 'Dedicated:'} ${s.dedication}`;
}

/**
 * @description Returns from the D'var Torah screen back to the welcome screen.
 * @returns {void}
 */
function hideDvarTorah() {
    dvarTorahScreen.classList.add('hidden');
    welcomeScreen.classList.remove('hidden');
}

/* ============================================================
 * JEWISH CALENDAR AWARENESS
 * Shows a respectful, dismissible banner on Shabbat, yom tov,
 * and their eves. Uses the client's local clock since Shabbat
 * depends on local sundown.
 * ============================================================ */

/**
 * @description Fetches Shabbat/yom tov status for the user's local time and shows
 *              a dismissible notice banner when applicable. Dismissal is remembered
 *              per message for the browser session.
 * @returns {Promise<void>}
 * @async
 */
async function checkCalendarStatus() {
    try {
        const now = new Date();
        const pad = n => String(n).padStart(2, '0');
        const localTime = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
            `T${pad(now.getHours())}:${pad(now.getMinutes())}:00`;

        const response = await fetch(`${API_BASE}/calendar-status?client_time=${encodeURIComponent(localTime)}`);
        if (!response.ok) return;

        const data = await response.json();
        const banner = document.getElementById('calendarBanner');
        if (!banner || !data.message) return;
        if (sessionStorage.getItem('calendarBannerDismissed') === data.message) return;

        banner.innerHTML = '';
        const text = document.createElement('span');
        text.className = 'calendar-banner-text';
        text.textContent = data.message;

        const close = document.createElement('button');
        close.className = 'calendar-banner-close';
        close.type = 'button';
        close.setAttribute('aria-label', 'Dismiss notice');
        const closeIcon = document.createElement('span');
        closeIcon.className = 'ph-icon ph-x';
        closeIcon.setAttribute('aria-hidden', 'true');
        close.appendChild(closeIcon);
        close.addEventListener('click', () => {
            banner.classList.add('hidden');
            sessionStorage.setItem('calendarBannerDismissed', data.message);
        });

        banner.appendChild(text);
        banner.appendChild(close);
        banner.classList.remove('hidden');
    } catch (error) {
        console.error('Calendar status check failed:', error);
    }
}

/* ============================================================
 * CONVERSATIONS CRUD
 * Create, read, update, and delete operations for persistent
 * chat conversations. Only available for authenticated users.
 * ============================================================ */

/**
 * @description Loads all conversations for the authenticated user from the server
 *              and renders them in the sidebar list.
 * @returns {Promise<void>}
 * @async
 */
async function loadConversations() {
    renderConversationsSkeleton();
    try {
        const response = await fetch(`${API_BASE}/conversations`);
        if (response.ok) {
            const data = await response.json();
            conversations = data.conversations || [];
            renderConversationsList();
        } else {
            // fetch() only rejects on network failures, not HTTP error status
            // codes - a 401/500 response lands here, not in the catch block.
            // Without this branch the skeleton rows rendered above would stay
            // in place indefinitely since nothing ever replaces them.
            console.error('Failed to load conversations:', response.status);
            conversations = [];
            renderConversationsList();
        }
    } catch (error) {
        console.error('Failed to load conversations:', error);
        conversations = [];
        renderConversationsList();
    }
}

/**
 * @description Renders 3-4 skeleton row placeholders into the sidebar conversation list
 *              while loadConversations() is fetching, replaced by real rows (or the
 *              empty state) once the fetch settles.
 * @returns {void}
 */
function renderConversationsSkeleton() {
    conversationsList.innerHTML = Array.from({ length: 4 }, () =>
        '<div class="skeleton skeleton-row"></div>'
    ).join('');
}

/**
 * @description Renders the sidebar conversation list from the in-memory conversations array.
 *              Each item includes a clickable title to load the conversation and a three-dot
 *              context menu with a delete option. The context menu dropdown is positioned
 *              using getBoundingClientRect() relative to the menu button so it works
 *              correctly inside the scrollable sidebar. Click handling is delegated to a
 *              single listener attached once in setupEventListeners() (see
 *              handleConversationsListClick) rather than re-attached on every render.
 * @returns {void}
 */
function renderConversationsList() {
    if (conversations.length === 0) {
        conversationsList.innerHTML = '<div class="conversations-empty">Your conversations will appear here after you ask a question.</div>';
        return;
    }

    conversationsList.innerHTML = conversations.map(conv => `
        <div class="conversation-item ${conv.id === currentConversationId ? 'active' : ''}" data-id="${conv.id}">
            <button class="conversation-open" type="button" ${conv.id === currentConversationId ? 'aria-current="page"' : ''}>
                <span class="conversation-title" dir="auto">${escapeHtml(conv.title || conv.first_message || 'New conversation')}</span>
            </button>
            <div class="conversation-menu">
                <button class="conversation-menu-btn" type="button" data-menu-id="${conv.id}" aria-label="Conversation options">
                    <span class="ph-icon ph-dots" aria-hidden="true"></span>
                </button>
                <div class="conversation-dropdown hidden" data-dropdown-id="${conv.id}">
                    <button class="dropdown-item dropdown-item-danger" type="button" data-delete-id="${conv.id}">
                        <span class="ph-icon ph-trash" aria-hidden="true"></span>
                        Delete
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

/**
 * @description Single delegated click handler for the sidebar conversation list, attached
 *              once to #conversationsList in setupEventListeners() instead of re-attaching
 *              fresh listeners to every item/button on each renderConversationsList() call.
 *              Uses event.target.closest() to figure out which element was clicked (item,
 *              menu button, or delete button) and dispatches to the same logic the old
 *              per-item listeners used, preserving behavior exactly.
 * @param {MouseEvent} e
 * @returns {void}
 */
function handleConversationsListClick(e) {
    // Delete button inside a dropdown takes priority over the menu button/item.
    const deleteBtn = e.target.closest('[data-delete-id]');
    if (deleteBtn && deleteBtn.classList.contains('dropdown-item')) {
        e.stopPropagation();
        const convId = deleteBtn.dataset.deleteId;
        deleteConversation(convId);
        return;
    }

    // Three-dot menu button toggles its associated dropdown.
    const menuBtn = e.target.closest('.conversation-menu-btn');
    if (menuBtn) {
        e.stopPropagation();
        e.preventDefault();
        const dropdown = menuBtn.parentElement.querySelector('.conversation-dropdown');

        // Close all other dropdowns first
        document.querySelectorAll('.conversation-dropdown').forEach(d => {
            if (d !== dropdown) d.classList.add('hidden');
        });

        if (dropdown) {
            // Position the fixed dropdown relative to button
            const rect = menuBtn.getBoundingClientRect();
            dropdown.style.top = `${rect.bottom + 4}px`;
            dropdown.style.left = `${rect.right - 140}px`; // Align to right edge
            dropdown.classList.toggle('hidden');
        }
        return;
    }

    // Clicking anywhere else in a conversation item (but not its menu) loads it.
    const item = e.target.closest('.conversation-item');
    if (item) {
        if (e.target.closest('.conversation-menu')) return;
        loadConversation(item.dataset.id);
    }
}

/**
 * @description Creates a new conversation on the server. Adds the new conversation to the
 *              front of the local conversations array and updates the sidebar.
 * @returns {Promise<string|null>} The new conversation's UUID, or null on failure
 * @async
 */
async function createConversation() {
    try {
        const response = await fetch(`${API_BASE}/conversations`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        if (response.ok) {
            const conversation = await response.json();
            currentConversationId = conversation.id;
            conversations.unshift(conversation);
            renderConversationsList();
            return conversation.id;
        }
    } catch (error) {
        console.error('Failed to create conversation:', error);
    }
    return null;
}

/**
 * @description Loads a specific conversation by ID from the server, populates the chat
 *              message area with its history, switches to the chat screen, and highlights
 *              the conversation in the sidebar.
 * @param {string} conversationId - UUID of the conversation to load
 * @returns {Promise<void>}
 * @async
 */
async function loadConversation(conversationId) {
    try {
        const response = await fetch(`${API_BASE}/conversations/${conversationId}`);
        if (response.ok) {
            const data = await response.json();
            currentConversationId = conversationId;
            conversationHistory = (data.messages || []).map(m => ({
                role: m.role,
                content: m.content
            }));

            // Update UI
            chatMessages.innerHTML = '';
            data.messages.forEach(msg => {
                addMessageToUI(msg.role, msg.content, new Date(msg.created_at), msg.id, msg.metadata);
            });

            // Update title
            chatTitle.textContent = data.title || 'New conversation';

            // Switch to chat screen
            welcomeScreen.classList.add('hidden');
            settingsScreen.classList.add('hidden');
            dvarTorahScreen.classList.add('hidden');
            chatScreen.classList.remove('hidden');

            // Update active state in sidebar
            renderConversationsList();

            // Close mobile sidebar
            closeSidebarMobile();

            scrollToBottom(true);
        }
    } catch (error) {
        console.error('Failed to load conversation:', error);
    }
}

/**
 * @description Deletes a conversation on the server and removes it from the local list.
 *              If the deleted conversation was currently active, navigates back to the
 *              welcome screen via startNewConversation().
 * @param {string} conversationId - UUID of the conversation to delete
 * @returns {Promise<void>}
 * @async
 */
async function deleteConversation(conversationId) {
    // Close any open dropdown
    document.querySelectorAll('.conversation-dropdown').forEach(d => d.classList.add('hidden'));

    try {
        const response = await fetch(`${API_BASE}/conversations/${conversationId}`, {
            method: 'DELETE'
        });
        if (response.ok) {
            conversations = conversations.filter(c => c.id !== conversationId);
            renderConversationsList();

            // If we deleted the current conversation, go back to welcome
            if (conversationId === currentConversationId) {
                startNewConversation();
            }
        }
    } catch (error) {
        console.error('Failed to delete conversation:', error);
    }
}

/* ============================================================
 * CHAT MESSAGING & STREAMING
 * Core chat functionality: sending messages, processing SSE
 * (Server-Sent Events) streams, and managing the streaming UI.
 * ============================================================ */

/**
 * @description Sends a message from the welcome screen. Creates a new server-side
 *              conversation (for authenticated users), transitions to the chat screen,
 *              and delegates to sendMessage().
 * @returns {Promise<void>}
 * @async
 */
async function sendFromWelcome() {
    const message = messageInput.value.trim();
    if (!message || isLoading) return;

    // Require sign-in before any submission. Preserve the typed prompt so
    // it can be restored in-place once the popup login completes.
    if (!currentUser) {
        savePendingDraft(message);
        showLoginPrompt();
        return;
    }

    const convId = await createConversation();
    if (!convId) {
        // Database might not be configured, continue without persistence
        console.warn('Could not create conversation, continuing without persistence');
    }

    // Switch to chat screen
    welcomeScreen.classList.add('hidden');
    settingsScreen.classList.add('hidden');
    dvarTorahScreen.classList.add('hidden');
    chatScreen.classList.remove('hidden');
    chatTitle.textContent = 'New conversation';

    // Clear welcome input
    messageInput.value = '';
    sendBtn.disabled = true;
    sendBtn.classList.add('loading');

    // Send the message
    sendMessage(message);
}

/**
 * @description Sends a message from the chat screen input. Clears the input, resets
 *              the textarea height, and delegates to sendMessage().
 * @returns {void}
 */
function sendFromChat() {
    const message = chatInput.value.trim();
    if (!message || isLoading) return;

    // Require sign-in before submitting a follow-up as well.
    if (!currentUser) {
        savePendingDraft(message);
        showLoginPrompt();
        return;
    }

    // Clear chat input
    chatInput.value = '';
    chatSendBtn.disabled = true;
    autoResize(chatInput);

    // Send the message
    sendMessage(message);
}

/**
 * @description Sends a user message through the multi-agent pipeline and streams the
 *              response using Server-Sent Events (SSE). This is the core chat function.
 *
 *              The SSE stream uses a ReadableStream reader to process chunks incrementally.
 *              Incoming bytes are decoded and accumulated in a buffer. The buffer is split
 *              on newline boundaries; incomplete lines are kept for the next iteration.
 *              Each complete line prefixed with "data: " is parsed as JSON.
 *
 *              SSE event types:
 *              - "session": Contains session_id and optional conversation_id
 *              - "metadata": Contains requires_human_referral flag from the moral agent
 *              - "token": A text chunk to append to the streaming response
 *              - "message_saved": The server-assigned message ID after persistence
 *              - "message_save_failed": Persistence failed - feedback buttons are
 *                hidden for this message since there's no message_id to attach them to
 *              - "error": An error from the pipeline (e.g., "guest_limit_reached")
 *
 * @param {string} message - The user's message text to send
 * @returns {Promise<void>}
 * @async
 */
async function sendMessage(message) {
    if (isLoading) return;

    // Safety net: sendFromWelcome/sendFromChat already require login before
    // calling sendMessage, but guard here too so a stray call can't slip
    // through.
    if (!currentUser) {
        savePendingDraft(message);
        showLoginPrompt();
        return;
    }

    // Add user message to chat
    addMessage('user', message);

    // Show loading state
    setLoading(true);
    showTypingIndicator();

    // Guard against a hung backend: abort the request if no response starts
    // arriving within ~90 seconds. Cleared as soon as the stream starts
    // receiving data below, so a slow-but-working multi-second stream is
    // never killed mid-stream.
    const abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort(), 90000);
    let streamStarted = false;

    try {
        const response = await fetch(`${API_BASE}/chat/stream`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                message: message,
                conversation_history: conversationHistory,
                session_id: sessionId,
                conversation_id: currentConversationId,
            }),
            signal: abortController.signal,
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        // Set up a ReadableStream reader to consume the SSE byte stream incrementally.
        // The TextDecoder is configured with { stream: true } to handle multi-byte UTF-8
        // characters that may be split across chunk boundaries.
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let fullResponse = '';
        let requiresHumanReferral = false;
        let pipelineMetadata = null; // Crisis flags, verified sources, pastoral mode
        let buffer = ''; // Accumulates partial lines between read() calls
        let messageElement = null;
        let savedMessageId = null;
        let messageSaveFailed = false;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            // The stream has started producing data - the timeout has done its
            // job of guarding against a hung connection, so cancel it now.
            // A slow-but-working stream (several seconds, per the multi-agent
            // pipeline) must not be killed once tokens are flowing.
            if (!streamStarted) {
                streamStarted = true;
                clearTimeout(timeoutId);
            }

            // Append decoded text to the buffer and split on newlines.
            // The last element (possibly incomplete) is kept in the buffer
            // for the next iteration via lines.pop().
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                // SSE lines are prefixed with "data: " followed by a JSON payload.
                // Lines without this prefix (e.g., empty keep-alive lines) are skipped.
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));

                        if (data.type === 'session') {
                            sessionId = data.session_id;
                            // Update conversation ID if provided
                            if (data.conversation_id) {
                                currentConversationId = data.conversation_id;
                            }
                        } else if (data.type === 'metadata') {
                            pipelineMetadata = data.data;
                            requiresHumanReferral = data.data.requires_human_referral;
                        } else if (data.type === 'token') {
                            if (!messageElement) {
                                removeTypingIndicator();
                                messageElement = createStreamingMessage();
                            }
                            fullResponse += data.data;
                            updateStreamingMessage(messageElement, fullResponse);
                        } else if (data.type === 'message_saved') {
                            savedMessageId = data.message_id;
                        } else if (data.type === 'message_save_failed') {
                            messageSaveFailed = true;
                        } else if (data.type === 'error') {
                            if (data.message === 'guest_limit_reached') {
                                // Guest has used their free chat - remove the user message we just added
                                const lastUserMessage = chatMessages.querySelector('.message.user:last-of-type');
                                if (lastUserMessage) {
                                    lastUserMessage.remove();
                                    conversationHistory.pop();
                                }
                                removeTypingIndicator();
                                setLoading(false);
                                // Preserve the prompt so it survives the sign-in flow
                                savePendingDraft(message);
                                showLoginPrompt();
                                return;
                            }
                            throw new Error(data.message);
                        }
                    } catch (e) {
                        // JSON parse errors in individual SSE lines are logged but
                        // do not abort the stream, allowing recovery from malformed events.
                        console.error('Error parsing SSE:', e, line);
                    }
                }
            }
        }

        if (messageElement) {
            finalizeStreamingMessage(messageElement, fullResponse, savedMessageId, messageSaveFailed, pipelineMetadata);
        } else {
            removeTypingIndicator();
            throw new Error('No response received');
        }

        if (requiresHumanReferral) {
            showReferralNotice();
        } else {
            hideReferralNotice();
        }

        // Update guest status after successful chat
        if (!currentUser) {
            await checkGuestStatus();
        }

        // Refresh conversations list to get updated title (only for logged-in users)
        if (currentUser) {
            await loadConversations();
        }

    } catch (error) {
        // Catch-all for network failures, HTTP errors, and unexpected stream errors.
        // Cleans up any in-progress streaming UI and shows a friendly error message.
        console.error('Error sending message:', error);
        removeTypingIndicator();
        const streamingMsg = document.getElementById('streamingMessage');
        if (streamingMsg) streamingMsg.remove();

        if (error.name === 'AbortError') {
            // The 90-second watchdog timeout fired because no data ever
            // started arriving - distinct message so the user knows to retry
            // rather than assuming a generic failure.
            const timeoutMessage = addMessage('assistant',
                "Request timed out, please try again."
            );
            timeoutMessage.classList.add('message-timeout');
            announce('The request timed out. Please try again.');
        } else {
            const errorMessage = addMessage('assistant',
                "I'm having trouble responding right now. Please try again in a moment."
            );
            errorMessage.classList.add('message-error');
            announce('The response could not be completed. Please try again.');
        }
    } finally {
        clearTimeout(timeoutId);
        setLoading(false);
    }
}

/**
 * @description Adds a message to both the UI and the in-memory conversation history.
 *              Caps the history at 20 messages (most recent) to limit token usage on
 *              subsequent API calls.
 * @param {string} role - Either 'user' or 'assistant'
 * @param {string} content - The message text content
 * @returns {void}
 */
function addMessage(role, content) {
    const messageElement = addMessageToUI(role, content, new Date());

    // Update conversation history
    conversationHistory.push({ role, content });

    // Keep only last 20 messages in history
    if (conversationHistory.length > 20) {
        conversationHistory = conversationHistory.slice(-20);
    }

    scrollToBottom(role === 'user');
    return messageElement;
}

/* ============================================================
 * MESSAGE RENDERING
 * Functions for creating, updating, and finalizing message DOM
 * elements including the streaming cursor animation and typing
 * indicator with rotating agent phase messages.
 * ============================================================ */

/**
 * @description Creates and appends a message bubble to the chat area. Assistant messages
 *              are rendered with Markdown formatting and receive action buttons (copy,
 *              speak, thumbs up/down).
 * @param {string} role - Either 'user' or 'assistant'
 * @param {string} content - The message text content
 * @param {Date} date - Timestamp to display in the message metadata
 * @param {string|null} [messageId=null] - Server-assigned message ID for feedback/TTS tracking
 * @returns {void}
 */
function addMessageToUI(role, content, date, messageId = null, metadata = null) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    if (messageId) {
        messageDiv.dataset.messageId = messageId;
    }

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.setAttribute('dir', 'auto');
    if (role === 'assistant') {
        contentDiv.innerHTML = formatMarkdown(content);
    } else {
        contentDiv.textContent = content;
    }

    const metaDiv = document.createElement('div');
    metaDiv.className = 'message-meta';

    const timeSpan = document.createElement('span');
    timeSpan.className = 'message-time';
    timeSpan.textContent = formatTime(date);

    metaDiv.appendChild(timeSpan);
    messageDiv.appendChild(contentDiv);

    // Citations for saved assistant messages (persisted pipeline metadata)
    if (role === 'assistant' && metadata) {
        const sourcesDiv = createSourcesFooter(metadata.sources);
        if (sourcesDiv) {
            messageDiv.appendChild(sourcesDiv);
        }
    }

    messageDiv.appendChild(metaDiv);

    // Add action buttons for assistant messages
    if (role === 'assistant') {
        const actionsDiv = createMessageActions(content, messageId);
        messageDiv.appendChild(actionsDiv);
    }

    chatMessages.appendChild(messageDiv);
    return messageDiv;
}

/* ============================================================
 * UI HELPERS
 * Utility functions for time formatting, HTML escaping,
 * Markdown rendering, scroll management, and toast notifications.
 * ============================================================ */

/**
 * @description Formats a Date object to a short time string (e.g., "2:30 PM").
 * @param {Date} date - The date to format
 * @returns {string} Locale-formatted time string with hours and minutes
 */
function formatTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/**
 * @description Escapes HTML special characters by using the browser's built-in DOM
 *              text encoding. Creates a temporary div, sets its textContent (which
 *              auto-escapes), and reads back the innerHTML.
 * @param {string} text - Raw text to escape
 * @returns {string} HTML-escaped string safe for insertion via innerHTML
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * @description Applies inline Markdown formatting (bold, italic, inline code) to a line
 *              of already-HTML-escaped text.
 * @param {string} s - HTML-escaped text
 * @returns {string} Text with inline formatting tags applied
 */
function formatInlineMarkdown(s) {
    return s
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');
}

/**
 * @description Converts Markdown to HTML with a line-based, dependency-free renderer.
 *              First escapes ALL input (XSS-safe), then handles headings, bullet and
 *              numbered lists, blockquotes, paragraphs, and line breaks in addition to
 *              bold/italic/inline code. Tolerant of partial input, so it is safe to call
 *              repeatedly on accumulating streamed text.
 * @param {string} text - Raw Markdown text from the assistant
 * @returns {string} HTML string
 */
function formatMarkdown(text) {
    const lines = escapeHtml(text).split('\n');
    const out = [];
    let listTag = null;   // 'ul' | 'ol' while inside a list
    let paragraph = [];

    const closeList = () => {
        if (listTag) { out.push(`</${listTag}>`); listTag = null; }
    };
    const flushParagraph = () => {
        if (paragraph.length) {
            out.push(`<p>${paragraph.join('<br>')}</p>`);
            paragraph = [];
        }
    };

    for (const raw of lines) {
        const trimmed = raw.trim();
        if (!trimmed) { flushParagraph(); closeList(); continue; }

        const heading = /^(#{1,4})\s+(.+)$/.exec(trimmed);
        const bullet = /^[-*•]\s+(.+)$/.exec(trimmed);
        const numbered = /^\d+[.)]\s+(.+)$/.exec(trimmed);
        const quote = /^&gt;\s?(.*)$/.exec(trimmed);

        if (heading) {
            flushParagraph(); closeList();
            // Map #/## -> h3, deeper -> h4/h5, sized for the chat column
            const level = Math.min(heading[1].length + 2, 5);
            out.push(`<h${level}>${formatInlineMarkdown(heading[2])}</h${level}>`);
        } else if (bullet) {
            flushParagraph();
            if (listTag !== 'ul') { closeList(); out.push('<ul>'); listTag = 'ul'; }
            out.push(`<li>${formatInlineMarkdown(bullet[1])}</li>`);
        } else if (numbered) {
            flushParagraph();
            if (listTag !== 'ol') { closeList(); out.push('<ol>'); listTag = 'ol'; }
            out.push(`<li>${formatInlineMarkdown(numbered[1])}</li>`);
        } else if (quote) {
            flushParagraph(); closeList();
            out.push(`<blockquote>${formatInlineMarkdown(quote[1])}</blockquote>`);
        } else {
            closeList();
            paragraph.push(formatInlineMarkdown(trimmed));
        }
    }
    flushParagraph();
    closeList();
    return out.join('');
}

/**
 * @description Builds the "Sources" footer for an assistant message from the pipeline
 *              metadata. Citations verified against passages actually retrieved from
 *              the text library get a checkmark; unverified ones (cited from the
 *              model's general knowledge) are labeled via tooltip.
 * @param {Array<{ref: string, verified: boolean}|string>} sources - Structured citations
 * @returns {HTMLElement|null} The footer element, or null when there are no sources
 */
function createSourcesFooter(sources) {
    if (!sources || !sources.length) return null;

    const div = document.createElement('div');
    div.className = 'message-sources';

    const label = document.createElement('span');
    label.className = 'sources-label';
    label.textContent = 'Sources';
    div.appendChild(label);

    sources.forEach(src => {
        const ref = typeof src === 'string' ? src : src.ref;
        if (!ref) return;
        const verified = typeof src === 'object' && !!src.verified;
        const chip = document.createElement('span');
        chip.className = 'source-chip' + (verified ? ' local-match' : ' model-knowledge');
        chip.setAttribute('dir', 'auto');
        chip.title = verified
            ? 'Matched to a passage retrieved from the text library for this answer'
            : "Cited from model knowledge and not matched against the local library";
        chip.textContent = `${verified ? 'Locally matched' : 'Model knowledge'}: ${ref}`;
        div.appendChild(chip);
    });

    return div.childElementCount > 1 ? div : null;
}

/**
 * @description Creates an empty assistant message element with a blinking cursor animation
 *              for the streaming response. The element is given id="streamingMessage" so it
 *              can be found and removed if streaming fails.
 * @returns {HTMLElement} The newly created message container div
 */
function createStreamingMessage() {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant';
    messageDiv.id = 'streamingMessage';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content streaming';
    contentDiv.setAttribute('dir', 'auto');
    contentDiv.innerHTML = '<span class="cursor"></span>';

    const metaDiv = document.createElement('div');
    metaDiv.className = 'message-meta';

    const timeSpan = document.createElement('span');
    timeSpan.className = 'message-time';
    timeSpan.textContent = formatTime(new Date());

    metaDiv.appendChild(timeSpan);
    messageDiv.appendChild(contentDiv);
    messageDiv.appendChild(metaDiv);
    chatMessages.appendChild(messageDiv);

    scrollToBottom();
    return messageDiv;
}

/**
 * @description Updates the streaming message at most once per animation frame using plain
 *              text. Markdown is applied once when the response is finalized.
 * @param {HTMLElement} messageElement - The streaming message container
 * @param {string} content - The full accumulated response text so far
 * @returns {void}
 */
function updateStreamingMessage(messageElement, content) {
    let state = streamingRenderState.get(messageElement);
    if (!state) {
        state = { content: '', frame: null };
        streamingRenderState.set(messageElement, state);
    }
    state.content = content;
    if (state.frame !== null) return;

    state.frame = requestAnimationFrame(() => {
        const contentDiv = messageElement.querySelector('.message-content');
        if (!contentDiv) return;
        contentDiv.textContent = state.content;
        const cursor = document.createElement('span');
        cursor.className = 'cursor';
        cursor.setAttribute('aria-hidden', 'true');
        contentDiv.appendChild(cursor);
        state.frame = null;
        scrollToBottom();
    });
}

/**
 * @description Finalizes a streaming message after the SSE stream completes. Removes the
 *              cursor animation, clears the temporary ID, attaches action buttons, and
 *              adds the complete message to conversation history.
 * @param {HTMLElement} messageElement - The streaming message container to finalize
 * @param {string} content - The complete response text
 * @param {string|null} [messageId=null] - Server-assigned message ID for feedback tracking
 * @param {boolean} [saveFailed=false] - True if the server reported the message
 *              could not be persisted (feedback buttons are hidden in this case
 *              rather than shown non-functional)
 * @returns {void}
 */
function finalizeStreamingMessage(messageElement, content, messageId = null, saveFailed = false, metadata = null) {
    const renderState = streamingRenderState.get(messageElement);
    if (renderState && renderState.frame !== null) cancelAnimationFrame(renderState.frame);
    streamingRenderState.delete(messageElement);
    const contentDiv = messageElement.querySelector('.message-content');
    contentDiv.innerHTML = formatMarkdown(content);
    contentDiv.classList.remove('streaming');
    messageElement.removeAttribute('id');

    if (messageId) {
        messageElement.dataset.messageId = messageId;
    }

    // Show the citations behind this answer (verified against the library
    // where possible) directly under the message content.
    const sourcesDiv = createSourcesFooter(metadata && metadata.sources);
    if (sourcesDiv) {
        contentDiv.after(sourcesDiv);
    }

    // Add action buttons if not already added
    if (!messageElement.querySelector('.message-actions')) {
        const actionsDiv = createMessageActions(content, messageId, saveFailed);
        messageElement.appendChild(actionsDiv);
    }

    conversationHistory.push({ role: 'assistant', content });

    if (conversationHistory.length > 20) {
        conversationHistory = conversationHistory.slice(-20);
    }
    announce('Response complete.');
}

/**
 * @type {Array<{name: string, phrase: string}>}
 * @description The four agent pipeline phases displayed in the typing indicator.
 *              Each phase corresponds to an agent in the backend multi-agent pipeline:
 *              Pastoral (emotional context), Halachic (legal reasoning), Moral (ethics check),
 *              and Voice (final response crafting). Phases rotate on a 2.5-second interval.
 */
const agentPhases = [
    { name: 'Pastoral', phrase: 'Listening with an open heart...' },
    { name: 'Halachic', phrase: 'Searching the sources...' },
    { name: 'Moral', phrase: 'Weighing with care...' },
    { name: 'Voice', phrase: 'Crafting a thoughtful response...' }
];
/** @type {number|null} Interval ID for the phase rotation timer */
let phaseInterval = null;
/** @type {number} Index into agentPhases for the currently displayed phase */
let currentPhaseIndex = 0;
/** @type {number|null} Interval ID for the elapsed-time ticker */
let elapsedInterval = null;
/** @type {number|null} Timestamp (ms) when the typing indicator was shown */
let typingStartTime = null;

/**
 * @description Shows an animated typing indicator that cycles through the four agent
 *              pipeline phases every 2.5 seconds with a fade transition. The indicator
 *              includes three animated dots alongside the phase text, plus a ticking
 *              elapsed-time readout so users have a sense of progress while the
 *              multi-agent backend pipeline runs (which can take several seconds).
 * @returns {void}
 */
function showTypingIndicator() {
    const typing = document.createElement('div');
    typing.className = 'message assistant';
    typing.id = 'typingIndicator';

    const indicator = document.createElement('div');
    indicator.className = 'message-content typing-indicator';
    indicator.setAttribute('aria-live', 'polite');
    indicator.innerHTML = `<div class="thinking-phase"><span class="phase-text">${agentPhases[0].phrase}</span><span class="phase-elapsed" id="phaseElapsed">0s</span><div class="phase-dots"><span></span><span></span><span></span></div></div>`;

    typing.appendChild(indicator);
    chatMessages.appendChild(typing);
    scrollToBottom();

    currentPhaseIndex = 0;
    phaseInterval = setInterval(() => {
        currentPhaseIndex = (currentPhaseIndex + 1) % agentPhases.length;
        const phaseText = document.querySelector('.phase-text');
        if (phaseText) {
            phaseText.classList.add('fading');
            setTimeout(() => {
                phaseText.textContent = agentPhases[currentPhaseIndex].phrase;
                phaseText.classList.remove('fading');
            }, 150);
        }
    }, 2500);

    // Ticking elapsed-time readout, incremented every second from when the
    // indicator was first shown until the response completes or is removed.
    typingStartTime = Date.now();
    elapsedInterval = setInterval(() => {
        const phaseElapsed = document.getElementById('phaseElapsed');
        if (phaseElapsed && typingStartTime) {
            const seconds = Math.floor((Date.now() - typingStartTime) / 1000);
            phaseElapsed.textContent = `${seconds}s`;
        }
    }, 1000);
}

/**
 * @description Removes the typing indicator from the DOM and clears the phase rotation
 *              and elapsed-time timers.
 * @returns {void}
 */
function removeTypingIndicator() {
    if (phaseInterval) {
        clearInterval(phaseInterval);
        phaseInterval = null;
    }
    if (elapsedInterval) {
        clearInterval(elapsedInterval);
        elapsedInterval = null;
    }
    typingStartTime = null;
    const typing = document.getElementById('typingIndicator');
    if (typing) {
        typing.remove();
    }
}

/**
 * @description Toggles the global loading state. Disables the send button while loading
 *              (unless the input is empty) and shows/hides the loading indicator.
 * @param {boolean} loading - Whether the app is in a loading state
 * @returns {void}
 */
function setLoading(loading) {
    isLoading = loading;
    chatSendBtn.disabled = loading || !chatInput.value.trim();
    chatSendBtn.classList.toggle('loading', loading);
    sendBtn.classList.toggle('loading', loading);
    loadingIndicator.classList.toggle('hidden', !loading);
    chatMessages.setAttribute('aria-busy', String(loading));
    if (loading) announce('Preparing a response.');
}

/**
 * @description Shows the human rabbi referral notice banner when the moral agent
 *              determines the user's question requires professional human guidance.
 * @returns {void}
 */
function showReferralNotice() {
    referralNotice.classList.remove('hidden');
    announce('A human rabbi or counselor may be helpful for this question.');
}

/**
 * @description Hides the human rabbi referral notice banner.
 * @returns {void}
 */
function hideReferralNotice() {
    referralNotice.classList.add('hidden');
}

/**
 * @description Resets the application to a clean state for a new conversation. Clears
 *              the message history, chat area, and all inputs. Navigates back to the
 *              welcome screen and focuses the welcome input after a short delay.
 * @returns {void}
 */
function startNewConversation() {
    // Reset state
    conversationHistory = [];
    sessionId = null;
    currentConversationId = null;

    // Clear messages
    chatMessages.innerHTML = '';

    // Hide referral notice
    hideReferralNotice();

    // Switch to welcome screen
    chatScreen.classList.add('hidden');
    settingsScreen.classList.add('hidden');
    dvarTorahScreen.classList.add('hidden');
    welcomeScreen.classList.remove('hidden');

    // Update sidebar
    renderConversationsList();

    // Reset inputs
    messageInput.value = '';
    chatInput.value = '';
    sendBtn.disabled = true;
    sendBtn.classList.remove('loading');
    chatSendBtn.disabled = true;
    chatSendBtn.classList.remove('loading');

    // Close mobile sidebar
    closeSidebarMobile();

    // Focus welcome input
    requestAnimationFrame(() => messageInput.focus());
}

/**
 * @description Scrolls to new content only while the reader is already following the
 *              bottom edge. A forced scroll is reserved for the reader's own messages
 *              and explicit conversation navigation.
 * @param {boolean} [force=false]
 * @returns {void}
 */
function scrollToBottom(force = false) {
    if (!force && !shouldAutoScroll) return;
    requestAnimationFrame(() => {
        chatMessages.scrollTop = chatMessages.scrollHeight;
        shouldAutoScroll = true;
    });
}

/** @returns {boolean} */
function isChatNearBottom() {
    return chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight < 120;
}

/**
 * Sends a concise status update to assistive technology without interrupting focus.
 * @param {string} message
 * @returns {void}
 */
function announce(message) {
    if (!appLiveRegion) return;
    appLiveRegion.textContent = '';
    requestAnimationFrame(() => { appLiveRegion.textContent = message; });
}

/* ============================================================
 * SETTINGS & PROFILE
 * Settings screen management, user profile CRUD, credit balance
 * display, and bio character counter.
 * ============================================================ */

/**
 * @description Navigates to the settings screen. Hides all other screens, populates
 *              user info, and loads credits and profile data in parallel.
 * @returns {Promise<void>}
 * @async
 */
async function showSettings() {
    // Hide other screens
    welcomeScreen.classList.add('hidden');
    chatScreen.classList.add('hidden');
    dvarTorahScreen.classList.add('hidden');
    settingsScreen.classList.remove('hidden');

    // Close mobile sidebar
    closeSidebarMobile();

    // Update profile info
    if (currentUser) {
        const firstName = currentUser.first_name || '';
        const lastName = currentUser.last_name || '';
        const fullName = [firstName, lastName].filter(Boolean).join(' ') || 'User';
        settingsUserName.textContent = fullName;
        settingsUserName.classList.remove('skeleton', 'settings-value-skeleton');
        settingsUserEmail.textContent = currentUser.email || '-';
        settingsUserEmail.classList.remove('skeleton', 'settings-value-skeleton');
    }

    // Load credits and profile in parallel
    await Promise.all([loadCredits(), loadProfile()]);
}

/**
 * @description Hides the settings screen and returns to either the active chat or
 *              the welcome screen, depending on whether a conversation is in progress.
 * @returns {void}
 */
function hideSettings() {
    settingsScreen.classList.add('hidden');

    // Show appropriate screen
    if (currentConversationId && conversationHistory.length > 0) {
        chatScreen.classList.remove('hidden');
    } else {
        welcomeScreen.classList.remove('hidden');
    }
}

/**
 * @description Fetches and displays the user's current credit balance from the server.
 *              Shows "Unlimited" for admin/unlimited accounts, the numeric balance for
 *              regular users, or "Error loading" on failure.
 * @returns {Promise<void>}
 * @async
 */
async function loadCredits() {
    // Only show the skeleton placeholder for the initial load. When this
    // function is called again later (e.g. refreshing the balance after a
    // purchase), the value already on screen should crossfade to the new
    // one via updateTextWithFade() instead of flashing back to a skeleton.
    const isInitialLoad = creditsValue.textContent.trim() === '';
    if (isInitialLoad) {
        creditsValue.classList.remove('credits-value');
        creditsValue.classList.add('skeleton', 'settings-value-skeleton');
    }

    try {
        const response = await fetch(`${API_BASE}/credits`);
        // Remove the skeleton before the fade helper runs so the crossfade is
        // visible immediately rather than being masked behind the skeleton
        // block for the duration of its 150ms transition.
        creditsValue.classList.remove('skeleton', 'settings-value-skeleton');

        if (response.ok) {
            const data = await response.json();
            if (data.unlimited) {
                updateTextWithFade(creditsValue, 'Unlimited');
                creditsValue.classList.remove('credits-value');
            } else {
                updateTextWithFade(creditsValue, String(data.credits));
                creditsValue.classList.add('credits-value');
            }
        } else {
            updateTextWithFade(creditsValue, 'Error loading');
        }
    } catch (error) {
        console.error('Failed to load credits:', error);
        creditsValue.classList.remove('skeleton', 'settings-value-skeleton');
        updateTextWithFade(creditsValue, 'Error loading');
    }
}

/**
 * @description Loads the user's profile data (denomination, bio) from the server and
 *              populates the settings form fields.
 * @returns {Promise<void>}
 * @async
 */
async function loadProfile() {
    try {
        const response = await fetch(`${API_BASE}/profile`);
        if (response.ok) {
            const data = await response.json();
            denominationSelect.value = data.denomination || '';
            bioInput.value = data.bio || '';
            updateBioCharCount();
        }
    } catch (error) {
        console.error('Failed to load profile:', error);
    }
}

/**
 * @description Saves the user's profile (denomination and bio) to the server via PUT.
 *              Shows a spinner during the request and a checkmark on success. Displays
 *              an alert on failure and re-enables the button in all cases.
 * @returns {Promise<void>}
 * @async
 */
async function saveProfile() {
    const originalText = saveProfileBtn.innerHTML;
    saveProfileBtn.disabled = true;
    saveProfileBtn.innerHTML = '<span class="saving-spinner" aria-hidden="true"></span> Saving...';

    try {
        const response = await fetch(`${API_BASE}/profile`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                denomination: denominationSelect.value || null,
                bio: bioInput.value || null,
            }),
        });

        if (response.ok) {
            saveProfileBtn.innerHTML = '<span class="ph-icon ph-check" aria-hidden="true"></span> Saved';
            announce('Profile saved successfully.');
            setTimeout(() => {
                saveProfileBtn.innerHTML = originalText;
                saveProfileBtn.disabled = false;
            }, 2000);
        } else {
            const errorData = await response.json();
            showToast(errorData.detail || 'Failed to save profile');
            announce('Profile could not be saved.');
            saveProfileBtn.innerHTML = originalText;
            saveProfileBtn.disabled = false;
        }
    } catch (error) {
        console.error('Failed to save profile:', error);
        showToast('Failed to save profile. Please try again.');
        announce('Profile could not be saved.');
        saveProfileBtn.innerHTML = originalText;
        saveProfileBtn.disabled = false;
    }
}

/**
 * @description Updates the bio character count display to reflect the current input length.
 * @returns {void}
 */
function updateBioCharCount() {
    const count = bioInput.value.length;
    bioCharCount.textContent = count;
}

/* ============================================================
 * MESSAGE ACTIONS
 * Action buttons on assistant messages: copy to clipboard,
 * text-to-speech via Web Audio API, and thumbs up/down feedback.
 * ============================================================ */

/**
 * @description Creates the action button toolbar for an assistant message. Includes
 *              copy, speak (TTS), thumbs-up, and thumbs-down buttons. Stores the message
 *              content and ID as data attributes on the container for use by handlers.
 * @param {string} content - The message text (used for copy and TTS)
 * @param {string|null} messageId - Server-assigned message ID (used for feedback API calls)
 * @param {boolean} [saveFailed=false] - True if the server reported this message could not
 *              be persisted; thumbs up/down are omitted since there's no message_id to
 *              attach feedback to (copy/speak still work since they don't need one)
 * @returns {HTMLElement} The action buttons container div
 */
function createMessageActions(content, messageId, saveFailed = false) {
    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'message-actions';

    actionsDiv.innerHTML = `
        <button class="action-btn copy-btn" type="button" aria-label="Copy response" title="Copy response" data-action="copy">
            <span class="ph-icon ph-copy" aria-hidden="true"></span>
        </button>
        <button class="action-btn speak-btn" type="button" aria-label="Listen to response" title="Listen" data-action="speak">
            <span class="ph-icon ph-speaker" aria-hidden="true"></span>
        </button>
        ${saveFailed ? '' : `
        <button class="action-btn thumbs-up-btn" type="button" aria-label="Mark as a good response" title="Good response" data-action="thumbs_up">
            <span class="ph-icon ph-thumbs-up" aria-hidden="true"></span>
        </button>
        <button class="action-btn thumbs-down-btn" type="button" aria-label="Mark as a poor response" title="Poor response" data-action="thumbs_down">
            <span class="ph-icon ph-thumbs-down" aria-hidden="true"></span>
        </button>`}
    `;

    // Store content for copy/speak
    actionsDiv.dataset.content = content;
    if (messageId) {
        actionsDiv.dataset.messageId = messageId;
    }

    // Add event listeners
    actionsDiv.querySelectorAll('.action-btn').forEach(btn => {
        btn.addEventListener('click', (e) => handleMessageAction(e, actionsDiv));
    });

    return actionsDiv;
}

// --- Web Audio API state for streaming PCM playback ---
/** @type {AudioContext|null} Shared AudioContext instance, initialized at 24kHz sample rate on first TTS use */
let audioContext = null;
/** @type {boolean} Whether TTS audio is currently playing */
let isPlaying = false;
/** @type {boolean} Flag to signal the streaming loop to cancel and stop all sources */
let stopRequested = false;
/** @type {Array<AudioBufferSourceNode>} All scheduled AudioBufferSourceNodes, tracked so they can be stopped immediately */
let activeSources = [];

/**
 * @description Dispatches a message action button click to the appropriate handler
 *              based on the button's data-action attribute.
 * @param {Event} event - The click event from an action button
 * @param {HTMLElement} actionsDiv - The actions container holding content and messageId data
 * @returns {void}
 */
function handleMessageAction(event, actionsDiv) {
    const button = event.currentTarget;
    const action = button.dataset.action;
    const content = actionsDiv.dataset.content;
    const messageId = actionsDiv.dataset.messageId;

    switch (action) {
        case 'copy':
            handleCopy(content);
            break;
        case 'speak':
            handleSpeak(content, button);
            break;
        case 'thumbs_up':
        case 'thumbs_down':
            handleFeedback(messageId, action, button, actionsDiv);
            break;
    }
}

/**
 * @description Copies the message content to the clipboard using the Clipboard API
 *              and shows a toast notification on success or failure.
 * @param {string} content - The text to copy to the clipboard
 * @returns {Promise<void>}
 * @async
 */
async function handleCopy(content) {
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
