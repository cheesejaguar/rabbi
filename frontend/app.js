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
const packageCards = document.querySelectorAll('.package-card');
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

// --- Stripe payment state ---
/** @type {Object|null} Stripe.js instance, initialized lazily on first modal open */
let stripe = null;
/** @type {Object|null} Stripe Elements instance bound to the current PaymentIntent client secret */
let elements = null;
/** @type {Object|null} Stripe PaymentElement mounted inside the purchase modal */
let paymentElement = null;
/** @type {string} Currently selected credit package identifier (e.g., 'credits_10', 'credits_25') */
let selectedPackage = 'credits_10';

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

    const firstName = currentUser.first_name || '';
    const lastName = currentUser.last_name || '';
    const email = currentUser.email || '';
    const fullName = [firstName, lastName].filter(Boolean).join(' ') || 'User';
    const initials = getInitials(firstName, lastName, email);

    // Update sidebar user info
    sidebarUserAvatar.textContent = initials;
    sidebarUserAvatar.style.fontSize = '';  // Reset font size from logged-out state
    sidebarUserName.textContent = fullName;

    // Restore logged-in dropdown content
    sidebarDropdown.innerHTML = `
        <button class="dropdown-item" id="settingsBtn">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="3"/>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
            Settings
        </button>
        <div class="dropdown-divider"></div>
        <a href="/auth/logout" class="dropdown-item dropdown-item-danger">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
                <polyline points="16 17 21 12 16 7"/>
                <line x1="21" y1="12" x2="9" y2="12"/>
            </svg>
            Logout
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
    sidebarUserAvatar.innerHTML = '&#x2192;';
    sidebarUserAvatar.style.fontSize = '1rem';
    sidebarUserName.textContent = 'Sign in';

    // Update dropdown to show login option
    sidebarDropdown.innerHTML = `
        <a href="/auth/login" class="dropdown-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>
                <polyline points="10 17 15 12 10 7"/>
                <line x1="15" y1="12" x2="3" y2="12"/>
            </svg>
            Sign In
        </a>
    `;
}

/**
 * @description Displays a login prompt banner at the bottom of the viewport. Creates the
 *              element on first call, then toggles visibility on subsequent calls.
 * @param {boolean} [showFreeChatsMessage=false] - If true, shows "Sign in for 3 more free chats"
 *                                                  instead of the default sign-in message
 * @returns {void}
 */
function showLoginPrompt(showFreeChatsMessage = false) {
    let prompt = document.getElementById('loginPrompt');
    const message = showFreeChatsMessage
        ? 'Sign in for 3 more free chats'
        : 'Please sign in to chat with rebbe.dev';

    if (!prompt) {
        prompt = document.createElement('div');
        prompt.id = 'loginPrompt';
        prompt.className = 'login-prompt';
        document.body.appendChild(prompt);
    }

    prompt.innerHTML = `
        <div class="login-prompt-content">
            <p>${message}</p>
            <a href="/auth/login" class="login-prompt-btn">Sign In</a>
            <button class="login-prompt-close" onclick="hideLoginPrompt()">&times;</button>
        </div>
    `;
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
    sidebarToggle.addEventListener('click', toggleSidebar);
    menuBtn.addEventListener('click', toggleSidebarMobile);
    welcomeMenuBtn.addEventListener('click', toggleSidebarMobile);
    sidebarOverlay.addEventListener('click', closeSidebarMobile);

    // New chat button
    newChatBtn.addEventListener('click', startNewConversation);

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
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', () => {
        sidebarDropdown.classList.add('hidden');
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
}

/**
 * @description Toggles sidebar visibility with responsive behavior. On mobile (<=768px),
 *              uses an overlay slide-in pattern. On desktop, toggles the collapsed state.
 * @returns {void}
 */
function toggleSidebarMobile() {
    // On mobile, use open/overlay behavior
    // On desktop with collapsed sidebar, toggle collapsed state
    const isMobile = window.innerWidth <= 768;

    if (isMobile) {
        sidebar.classList.toggle('open');
        sidebarOverlay.classList.toggle('visible');
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
    sidebar.classList.remove('open');
    sidebarOverlay.classList.remove('visible');
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
 * @returns {Promise<void>}
 * @async
 */
async function loadDvarTorah() {
    try {
        const response = await fetch(`${API_BASE}/dvar-torah`);
        if (!response.ok) return;

        const data = await response.json();
        if (data.is_holiday_week || !data.content) return;

        dvarTorahData = data;
        dvarTorahParsha.textContent = `${data.parsha_name} / ${data.parsha_name_hebrew}`;
        dvarTorahPreview.textContent = data.content.substring(0, 200) + '...';
        dvarTorahSection.classList.remove('hidden');
    } catch (error) {
        console.error('Failed to load d\'var Torah:', error);
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

    // Convert plain text to paragraphs
    const paragraphs = dvarTorahData.content.split('\n\n').filter(p => p.trim());
    const html = paragraphs.map(p => `<p>${p.replace(/\n/g, ' ')}</p>`).join('');
    dvarTorahScreenContent.innerHTML = `<div class="dvar-torah-body">${html}</div>`;
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
    try {
        const response = await fetch(`${API_BASE}/conversations`);
        if (response.ok) {
            const data = await response.json();
            conversations = data.conversations || [];
            renderConversationsList();
        }
    } catch (error) {
        console.error('Failed to load conversations:', error);
        conversations = [];
        renderConversationsList();
    }
}

/**
 * @description Renders the sidebar conversation list from the in-memory conversations array.
 *              Each item includes a clickable title to load the conversation and a three-dot
 *              context menu with a delete option. The context menu dropdown is positioned
 *              using getBoundingClientRect() relative to the menu button so it works
 *              correctly inside the scrollable sidebar.
 * @returns {void}
 */
function renderConversationsList() {
    if (conversations.length === 0) {
        conversationsList.innerHTML = '<div class="conversations-empty">No conversations yet</div>';
        return;
    }

    conversationsList.innerHTML = conversations.map(conv => `
        <div class="conversation-item ${conv.id === currentConversationId ? 'active' : ''}" data-id="${conv.id}">
            <span class="conversation-title">${escapeHtml(conv.title || conv.first_message || 'New conversation')}</span>
            <div class="conversation-menu">
                <button class="conversation-menu-btn" data-menu-id="${conv.id}" aria-label="Conversation options">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <circle cx="5" cy="12" r="2"/>
                        <circle cx="12" cy="12" r="2"/>
                        <circle cx="19" cy="12" r="2"/>
                    </svg>
                </button>
                <div class="conversation-dropdown hidden" data-dropdown-id="${conv.id}">
                    <button class="dropdown-item dropdown-item-danger" data-delete-id="${conv.id}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                        </svg>
                        Delete
                    </button>
                </div>
            </div>
        </div>
    `).join('');

    // Add click handlers for conversation items
    conversationsList.querySelectorAll('.conversation-item').forEach(item => {
        item.addEventListener('click', (e) => {
            // Don't load conversation if clicking menu
            if (e.target.closest('.conversation-menu')) return;
            loadConversation(item.dataset.id);
        });
    });

    // Add click handlers for menu buttons
    conversationsList.querySelectorAll('.conversation-menu-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            const dropdown = btn.parentElement.querySelector('.conversation-dropdown');

            // Close all other dropdowns first
            document.querySelectorAll('.conversation-dropdown').forEach(d => {
                if (d !== dropdown) d.classList.add('hidden');
            });

            if (dropdown) {
                // Position the fixed dropdown relative to button
                const rect = btn.getBoundingClientRect();
                dropdown.style.top = `${rect.bottom + 4}px`;
                dropdown.style.left = `${rect.right - 140}px`; // Align to right edge
                dropdown.classList.toggle('hidden');
            }
        });
    });

    // Add click handlers for delete buttons
    conversationsList.querySelectorAll('[data-delete-id]').forEach(btn => {
        if (btn.classList.contains('dropdown-item')) {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const convId = btn.dataset.deleteId;
                deleteConversation(convId);
            });
        }
    });
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
                addMessageToUI(msg.role, msg.content, new Date(msg.created_at), msg.id);
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

            scrollToBottom();
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

    // Only create conversation for logged-in users
    if (currentUser) {
        const convId = await createConversation();
        if (!convId) {
            // Database might not be configured, continue without persistence
            console.warn('Could not create conversation, continuing without persistence');
        }
    }

    // Switch to chat screen
    welcomeScreen.classList.add('hidden');
    settingsScreen.classList.add('hidden');
    dvarTorahScreen.classList.add('hidden');
    chatScreen.classList.remove('hidden');
    chatTitle.textContent = currentUser ? 'New conversation' : 'Guest chat';

    // Clear welcome input
    messageInput.value = '';
    sendBtn.disabled = true;

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
 *              - "error": An error from the pipeline (e.g., "guest_limit_reached")
 *
 * @param {string} message - The user's message text to send
 * @returns {Promise<void>}
 * @async
 */
async function sendMessage(message) {
    if (isLoading) return;

    // Check if user is authenticated or is a guest with remaining chats
    if (!currentUser) {
        // For guests, check if they have remaining free chats
        if (!guestStatus || guestStatus.chats_remaining <= 0) {
            showLoginPrompt(true); // true = show "3 more free chats" message
            return;
        }
    }

    // Add user message to chat
    addMessage('user', message);

    // Show loading state
    setLoading(true);
    showTypingIndicator();

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
        let buffer = ''; // Accumulates partial lines between read() calls
        let messageElement = null;
        let savedMessageId = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

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
                                showLoginPrompt(true);
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
            finalizeStreamingMessage(messageElement, fullResponse, savedMessageId);
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
        addMessage('assistant',
            "I'm having trouble responding right now. Please try again in a moment."
        );
    } finally {
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
    addMessageToUI(role, content, new Date());

    // Update conversation history
    conversationHistory.push({ role, content });

    // Keep only last 20 messages in history
    if (conversationHistory.length > 20) {
        conversationHistory = conversationHistory.slice(-20);
    }

    scrollToBottom();
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
function addMessageToUI(role, content, date, messageId = null) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    if (messageId) {
        messageDiv.dataset.messageId = messageId;
    }

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
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
    messageDiv.appendChild(metaDiv);

    // Add action buttons for assistant messages
    if (role === 'assistant') {
        const actionsDiv = createMessageActions(content, messageId);
        messageDiv.appendChild(actionsDiv);
    }

    chatMessages.appendChild(messageDiv);
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
 * @description Converts a subset of Markdown to HTML using a regex-based formatting pipeline.
 *              First escapes HTML to prevent XSS, then applies transformations:
 *              1. **bold** -> <strong>bold</strong>
 *              2. *italic* -> <em>italic</em>
 *              This is intentionally minimal; full Markdown parsing is not needed for
 *              the rabbinic response format.
 * @param {string} text - Raw Markdown text from the assistant
 * @returns {string} HTML string with basic formatting applied
 */
function formatMarkdown(text) {
    let html = escapeHtml(text);
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    return html;
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
 * @description Updates the content of a streaming message element with new text. Re-renders
 *              the full accumulated content through formatMarkdown on each call, appending
 *              the blinking cursor span.
 * @param {HTMLElement} messageElement - The streaming message container
 * @param {string} content - The full accumulated response text so far
 * @returns {void}
 */
function updateStreamingMessage(messageElement, content) {
    const contentDiv = messageElement.querySelector('.message-content');
    contentDiv.innerHTML = formatMarkdown(content) + '<span class="cursor"></span>';
    scrollToBottom();
}

/**
 * @description Finalizes a streaming message after the SSE stream completes. Removes the
 *              cursor animation, clears the temporary ID, attaches action buttons, and
 *              adds the complete message to conversation history.
 * @param {HTMLElement} messageElement - The streaming message container to finalize
 * @param {string} content - The complete response text
 * @param {string|null} [messageId=null] - Server-assigned message ID for feedback tracking
 * @returns {void}
 */
function finalizeStreamingMessage(messageElement, content, messageId = null) {
    const contentDiv = messageElement.querySelector('.message-content');
    contentDiv.innerHTML = formatMarkdown(content);
    contentDiv.classList.remove('streaming');
    messageElement.removeAttribute('id');

    if (messageId) {
        messageElement.dataset.messageId = messageId;
    }

    // Add action buttons if not already added
    if (!messageElement.querySelector('.message-actions')) {
        const actionsDiv = createMessageActions(content, messageId);
        messageElement.appendChild(actionsDiv);
    }

    conversationHistory.push({ role: 'assistant', content });

    if (conversationHistory.length > 20) {
        conversationHistory = conversationHistory.slice(-20);
    }
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

/**
 * @description Shows an animated typing indicator that cycles through the four agent
 *              pipeline phases every 2.5 seconds with a fade transition. The indicator
 *              includes three animated dots alongside the phase text.
 * @returns {void}
 */
function showTypingIndicator() {
    const typing = document.createElement('div');
    typing.className = 'message assistant';
    typing.id = 'typingIndicator';

    const indicator = document.createElement('div');
    indicator.className = 'message-content typing-indicator';
    indicator.innerHTML = `<div class="thinking-phase"><span class="phase-text">${agentPhases[0].phrase}</span><div class="phase-dots"><span></span><span></span><span></span></div></div>`;

    typing.appendChild(indicator);
    chatMessages.appendChild(typing);
    scrollToBottom();

    currentPhaseIndex = 0;
    phaseInterval = setInterval(() => {
        currentPhaseIndex = (currentPhaseIndex + 1) % agentPhases.length;
        const phaseText = document.querySelector('.phase-text');
        if (phaseText) {
            phaseText.style.opacity = '0';
            setTimeout(() => {
                phaseText.textContent = agentPhases[currentPhaseIndex].phrase;
                phaseText.style.opacity = '1';
            }, 150);
        }
    }, 2500);
}

/**
 * @description Removes the typing indicator from the DOM and clears the phase rotation interval.
 * @returns {void}
 */
function removeTypingIndicator() {
    if (phaseInterval) {
        clearInterval(phaseInterval);
        phaseInterval = null;
    }
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
    loadingIndicator.classList.toggle('hidden', !loading);
}

/**
 * @description Shows the human rabbi referral notice banner when the moral agent
 *              determines the user's question requires professional human guidance.
 * @returns {void}
 */
function showReferralNotice() {
    referralNotice.classList.remove('hidden');
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
    chatSendBtn.disabled = true;

    // Close mobile sidebar
    closeSidebarMobile();

    // Focus welcome input
    setTimeout(() => messageInput.focus(), 300);
}

/**
 * @description Scrolls the chat message container to the bottom after a 100ms delay.
 *              The delay ensures the DOM has been updated before measuring scrollHeight.
 * @returns {void}
 */
function scrollToBottom() {
    setTimeout(() => {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }, 100);
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
        settingsUserEmail.textContent = currentUser.email || '-';
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
    creditsValue.textContent = 'Loading...';
    creditsValue.classList.remove('credits-value');

    try {
        const response = await fetch(`${API_BASE}/credits`);
        if (response.ok) {
            const data = await response.json();
            if (data.unlimited) {
                creditsValue.textContent = 'Unlimited';
            } else {
                creditsValue.textContent = data.credits;
                creditsValue.classList.add('credits-value');
            }
        } else {
            creditsValue.textContent = 'Error loading';
        }
    } catch (error) {
        console.error('Failed to load credits:', error);
        creditsValue.textContent = 'Error loading';
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
    saveProfileBtn.innerHTML = '<span class="saving-spinner"></span> Saving...';

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
            saveProfileBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Saved!';
            setTimeout(() => {
                saveProfileBtn.innerHTML = originalText;
                saveProfileBtn.disabled = false;
            }, 2000);
        } else {
            const errorData = await response.json();
            alert(errorData.detail || 'Failed to save profile');
            saveProfileBtn.innerHTML = originalText;
            saveProfileBtn.disabled = false;
        }
    } catch (error) {
        console.error('Failed to save profile:', error);
        alert('Failed to save profile. Please try again.');
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
 * @returns {HTMLElement} The action buttons container div
 */
function createMessageActions(content, messageId) {
    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'message-actions';

    actionsDiv.innerHTML = `
        <button class="action-btn copy-btn" title="Copy response" data-action="copy">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
            </svg>
        </button>
        <button class="action-btn speak-btn" title="Listen" data-action="speak">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
                <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
            </svg>
        </button>
        <button class="action-btn thumbs-up-btn" title="Good response" data-action="thumbs_up">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
            </svg>
        </button>
        <button class="action-btn thumbs-down-btn" title="Poor response" data-action="thumbs_down">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/>
            </svg>
        </button>
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
        submitPayment.textContent = 'Pay Now';
    }

    // Reset package selection
    selectedPackage = 'credits_10';
    packageCards.forEach(card => {
        card.classList.toggle('selected', card.dataset.package === 'credits_10');
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
        card.classList.toggle('selected', card.dataset.package === packageId);
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
            appearance: {
                theme: 'night',
                variables: {
                    colorPrimary: '#d4a853',
                    colorBackground: '#1a1a1a',
                    colorText: '#e8e8e8',
                    colorDanger: '#ef4444',
                    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, sans-serif',
                    borderRadius: '8px',
                    spacingUnit: '4px',
                }
            }
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
        paymentElementContainer.innerHTML = `<p class="payment-error-text">${error.message || 'Failed to load payment form. Please try again.'}</p>`;
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
    submitPayment.textContent = 'Processing...';

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
            submitPayment.textContent = 'Pay Now';
        } else if (paymentIntent && paymentIntent.status === 'succeeded') {
            // Payment succeeded - try to verify and fulfill immediately (non-production only)
            submitPayment.textContent = 'Adding credits...';

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
        submitPayment.textContent = 'Pay Now';
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
