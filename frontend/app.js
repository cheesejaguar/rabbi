/**
 * rebbe.dev - Modern Frontend Application
 */

// Configuration
const API_BASE = '/api';

// State
let conversationHistory = [];
let sessionId = null;
let currentConversationId = null;
let conversations = [];
let isLoading = false;
let currentUser = null;

// Analytics session ID (persists across page loads within same browser session)
let analyticsSessionId = sessionStorage.getItem('analyticsSessionId');
if (!analyticsSessionId) {
    analyticsSessionId = 'sess_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    sessionStorage.setItem('analyticsSessionId', analyticsSessionId);
}

// Analytics helper function
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
        // Silently fail - analytics shouldn't break the app
    }
}

// TTS event tracking
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
        // Silently fail
    }
}

// DOM Elements
const welcomeScreen = document.getElementById('welcomeScreen');
const chatScreen = document.getElementById('chatScreen');
const greetingText = document.getElementById('greetingText');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const chatInput = document.getElementById('chatInput');
const chatSendBtn = document.getElementById('chatSendBtn');
const chatMessages = document.getElementById('chatMessages');
const chatTitle = document.getElementById('chatTitle');
const referralNotice = document.getElementById('referralNotice');
const loadingIndicator = document.getElementById('loadingIndicator');
const suggestionChips = document.querySelectorAll('.suggestion-chip');

// Sidebar elements
const sidebar = document.getElementById('sidebar');
const sidebarToggle = document.getElementById('sidebarToggle');
const sidebarOverlay = document.getElementById('sidebarOverlay');
const menuBtn = document.getElementById('menuBtn');
const welcomeMenuBtn = document.getElementById('welcomeMenuBtn');
const newChatBtn = document.getElementById('newChatBtn');
const conversationsList = document.getElementById('conversationsList');
const sidebarUserAvatar = document.getElementById('sidebarUserAvatar');
const sidebarUserName = document.getElementById('sidebarUserName');
const userProfile = document.getElementById('userProfile');
const sidebarUserMenuToggle = document.getElementById('sidebarUserMenuToggle');
const sidebarDropdown = document.getElementById('sidebarDropdown');
const settingsScreen = document.getElementById('settingsScreen');
const settingsBtn = document.getElementById('settingsBtn');
const settingsBackBtn = document.getElementById('settingsBackBtn');
const creditsValue = document.getElementById('creditsValue');
const settingsUserName = document.getElementById('settingsUserName');
const settingsUserEmail = document.getElementById('settingsUserEmail');

// Payment modal elements
const purchaseModal = document.getElementById('purchaseModal');
const buyCreditsBtn = document.getElementById('buyCreditsBtn');
const closePurchaseModal = document.getElementById('closePurchaseModal');
const packageCards = document.querySelectorAll('.package-card');
const submitPayment = document.getElementById('submitPayment');
const paymentElementContainer = document.getElementById('paymentElementContainer');
const packageSelection = document.getElementById('packageSelection');
const modalFooter = document.getElementById('modalFooter');
const paymentStatus = document.getElementById('paymentStatus');
const paymentSuccess = document.getElementById('paymentSuccess');
const paymentError = document.getElementById('paymentError');
const paymentErrorMessage = document.getElementById('paymentErrorMessage');

// Stripe payment state
let stripe = null;
let elements = null;
let paymentElement = null;
let selectedPackage = 'credits_10';

// Initialize
document.addEventListener('DOMContentLoaded', init);

async function init() {
    // Show logged-out state immediately (will be updated if authenticated)
    showLoggedOutState();

    // Track session start (only once per browser session)
    if (!sessionStorage.getItem('sessionTracked')) {
        trackEvent('session_start', { new_session: true });
        sessionStorage.setItem('sessionTracked', 'true');
    }
    // Always track page view
    trackEvent('page_view');

    // Check authentication first
    const isAuthenticated = await checkAuth();

    // Always setup event listeners (some work when logged out)
    setupEventListeners();

    if (!isAuthenticated) {
        // Show logged-out state in UI
        showLoggedOutState();
        return;
    }

    await Promise.all([
        loadGreeting(),
        loadConversations()
    ]);
}

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

function showLoginPrompt() {
    let prompt = document.getElementById('loginPrompt');
    if (!prompt) {
        prompt = document.createElement('div');
        prompt.id = 'loginPrompt';
        prompt.className = 'login-prompt';
        prompt.innerHTML = `
            <div class="login-prompt-content">
                <p>Please sign in to chat with rebbe.dev</p>
                <a href="/auth/login" class="login-prompt-btn">Sign In</a>
                <button class="login-prompt-close" onclick="hideLoginPrompt()">&times;</button>
            </div>
        `;
        document.body.appendChild(prompt);
    }
    prompt.classList.add('visible');
}

function hideLoginPrompt() {
    const prompt = document.getElementById('loginPrompt');
    if (prompt) {
        prompt.classList.remove('visible');
    }
}

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

    // User menu in sidebar - entire profile area is clickable
    userProfile.addEventListener('click', (e) => {
        e.stopPropagation();
        // Position the fixed dropdown above the profile
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

function toggleSidebar() {
    sidebar.classList.toggle('collapsed');
}

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

function closeSidebarMobile() {
    sidebar.classList.remove('open');
    sidebarOverlay.classList.remove('visible');
}

function handleWelcomeKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendFromWelcome();
    }
}

function handleChatKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendFromChat();
    }
}

function handleTextareaInput(textarea, button) {
    const hasContent = textarea.value.trim().length > 0;
    button.disabled = !hasContent;
    autoResize(textarea);
}

function autoResize(textarea) {
    textarea.style.height = 'auto';
    const maxHeight = textarea === messageInput ? 200 : 150;
    textarea.style.height = Math.min(textarea.scrollHeight, maxHeight) + 'px';
}

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

// Conversation management
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

async function sendFromWelcome() {
    const message = messageInput.value.trim();
    if (!message || isLoading) return;

    // Create a new conversation first
    const convId = await createConversation();
    if (!convId && currentUser) {
        // Database might not be configured, continue without persistence
        console.warn('Could not create conversation, continuing without persistence');
    }

    // Switch to chat screen
    welcomeScreen.classList.add('hidden');
    settingsScreen.classList.add('hidden');
    chatScreen.classList.remove('hidden');
    chatTitle.textContent = 'New conversation';

    // Clear welcome input
    messageInput.value = '';
    sendBtn.disabled = true;

    // Send the message
    sendMessage(message);
}

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

async function sendMessage(message) {
    if (isLoading) return;

    // Check if user is authenticated
    if (!currentUser) {
        showLoginPrompt();
        return;
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

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let fullResponse = '';
        let requiresHumanReferral = false;
        let buffer = '';
        let messageElement = null;
        let savedMessageId = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
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
                            throw new Error(data.message);
                        }
                    } catch (e) {
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

        // Refresh conversations list to get updated title
        await loadConversations();

    } catch (error) {
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

function formatTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatMarkdown(text) {
    let html = escapeHtml(text);
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    return html;
}

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

function updateStreamingMessage(messageElement, content) {
    const contentDiv = messageElement.querySelector('.message-content');
    contentDiv.innerHTML = formatMarkdown(content) + '<span class="cursor"></span>';
    scrollToBottom();
}

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

const agentPhases = [
    { name: 'Pastoral', phrase: 'Listening with an open heart...' },
    { name: 'Halachic', phrase: 'Searching the sources...' },
    { name: 'Moral', phrase: 'Weighing with care...' },
    { name: 'Voice', phrase: 'Crafting a thoughtful response...' }
];
let phaseInterval = null;
let currentPhaseIndex = 0;

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

function setLoading(loading) {
    isLoading = loading;
    chatSendBtn.disabled = loading || !chatInput.value.trim();
    loadingIndicator.classList.toggle('hidden', !loading);
}

function showReferralNotice() {
    referralNotice.classList.remove('hidden');
}

function hideReferralNotice() {
    referralNotice.classList.add('hidden');
}

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

function scrollToBottom() {
    setTimeout(() => {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }, 100);
}

// Settings functions
async function showSettings() {
    // Hide other screens
    welcomeScreen.classList.add('hidden');
    chatScreen.classList.add('hidden');
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

    // Load credits
    await loadCredits();
}

function hideSettings() {
    settingsScreen.classList.add('hidden');

    // Show appropriate screen
    if (currentConversationId && conversationHistory.length > 0) {
        chatScreen.classList.remove('hidden');
    } else {
        welcomeScreen.classList.remove('hidden');
    }
}

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

// Message action buttons
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

// Current audio for speak functionality
// Web Audio API for streaming PCM playback
let audioContext = null;
let isPlaying = false;
let stopRequested = false;
let activeSources = []; // Track all scheduled sources for stop functionality

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

async function handleCopy(content) {
    try {
        await navigator.clipboard.writeText(content);
        showToast('Copied to clipboard');
    } catch (error) {
        console.error('Failed to copy:', error);
        showToast('Failed to copy');
    }
}

async function handleSpeak(content, button) {
    // Initialize AudioContext on first use - must happen in user gesture
    // Set sample rate to 24kHz to match ElevenLabs PCM output
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

    // If already playing, stop all sources
    if (isPlaying) {
        stopRequested = true;
        // Stop all active sources immediately
        for (const source of activeSources) {
            try {
                source.stop();
            } catch (e) {
                // Source may have already stopped
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

        const reader = response.body.getReader();
        let nextStartTime = audioContext.currentTime;
        let firstChunk = true;
        let lastSource = null;
        let leftoverBytes = new Uint8Array(0);

        while (true) {
            if (stopRequested) {
                await reader.cancel();
                break;
            }

            const { done, value } = await reader.read();
            if (done) break;

            // Combine with any leftover bytes from previous chunk
            const combined = new Uint8Array(leftoverBytes.length + value.length);
            combined.set(leftoverBytes);
            combined.set(value, leftoverBytes.length);

            // PCM 16-bit needs even number of bytes
            const usableLength = combined.length - (combined.length % 2);
            leftoverBytes = combined.slice(usableLength);
            const pcmData = combined.slice(0, usableLength);

            if (pcmData.length === 0) continue;

            // Convert Int16 PCM to Float32 using DataView for explicit little-endian handling
            const numSamples = pcmData.length / 2;
            const float32 = new Float32Array(numSamples);
            const dataView = new DataView(pcmData.buffer, pcmData.byteOffset, pcmData.byteLength);
            for (let i = 0; i < numSamples; i++) {
                const int16Value = dataView.getInt16(i * 2, true); // true = little-endian
                float32[i] = int16Value / 32768;
            }

            // Create AudioBuffer
            const audioBuffer = audioContext.createBuffer(1, float32.length, PCM_SAMPLE_RATE);
            audioBuffer.getChannelData(0).set(float32);

            // Create source and schedule playback
            const source = audioContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(audioContext.destination);

            // Track source for stop functionality
            activeSources.push(source);

            // Schedule to play after previous chunk
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

        // When last chunk finishes playing
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
        console.error('Speech generation failed:', error);
        button.classList.remove('loading', 'playing');
        isPlaying = false;
        activeSources = [];
        showToast('Could not generate speech');
        // Track error
        trackTTSEvent('error', messageId, textLength, null, error.message || 'Unknown error');
    }
}

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
        console.error('Failed to save feedback:', error);
        showToast('Could not save feedback');
    }
}

// Toast notification
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

// ========================================
// Payment Modal Functions
// ========================================

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

function selectPackage(packageId) {
    selectedPackage = packageId;
    packageCards.forEach(card => {
        card.classList.toggle('selected', card.dataset.package === packageId);
    });

    // Reinitialize payment form with new package
    initializePaymentForm();
}

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

async function initializePaymentForm() {
    if (!paymentElementContainer || !submitPayment) return;

    submitPayment.disabled = true;
    paymentElementContainer.innerHTML = '<div class="payment-loading">Loading payment form...</div>';

    try {
        // Create payment intent
        const response = await fetch(`${API_BASE}/payments/create-intent`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ package_id: selectedPackage })
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
        console.error('Failed to initialize payment form:', error);
        paymentElementContainer.innerHTML = `<p class="payment-error-text">${error.message || 'Failed to load payment form. Please try again.'}</p>`;
    }
}

async function handlePaymentSubmit() {
    if (!stripe || !elements || !submitPayment) return;

    submitPayment.disabled = true;
    submitPayment.textContent = 'Processing...';

    try {
        const { error } = await stripe.confirmPayment({
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
        } else {
            // Payment succeeded without redirect
            showPaymentSuccessMessage();
            // Refresh credits display
            await loadCredits();
            // Close modal after delay
            setTimeout(closePurchaseModalHandler, 2000);
        }
    } catch (err) {
        console.error('Payment error:', err);
        showPaymentErrorMessage('An unexpected error occurred.');
        submitPayment.disabled = false;
        submitPayment.textContent = 'Pay Now';
    }
}

function showPaymentSuccessMessage() {
    if (packageSelection) packageSelection.classList.add('hidden');
    if (paymentElementContainer) paymentElementContainer.classList.add('hidden');
    if (modalFooter) modalFooter.classList.add('hidden');
    if (paymentStatus) paymentStatus.classList.remove('hidden');
    if (paymentSuccess) paymentSuccess.classList.remove('hidden');
}

function showPaymentErrorMessage(message) {
    if (paymentErrorMessage) paymentErrorMessage.textContent = message;
    if (paymentError) {
        paymentError.classList.remove('hidden');
        setTimeout(() => {
            paymentError.classList.add('hidden');
        }, 5000);
    }
}
