/**
 * AI Rabbi - Frontend Application
 * Mobile-optimized chatbot with Jewish themes
 */

// Configuration
const API_BASE = '/api';

// State
let conversationHistory = [];
let sessionId = null;
let isLoading = false;

// DOM Elements
const chatMessages = document.getElementById('chatMessages');
const messageInput = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');
const loadingOverlay = document.getElementById('loadingOverlay');
const referralNotice = document.getElementById('referralNotice');
const disclaimerBanner = document.getElementById('disclaimerBanner');

// Initialize
document.addEventListener('DOMContentLoaded', init);

async function init() {
    setupEventListeners();
    autoResizeTextarea();
    await loadGreeting();

    // Check if disclaimer was previously dismissed
    if (localStorage.getItem('disclaimerDismissed') === 'true') {
        disclaimerBanner.classList.add('hidden');
    }
}

function setupEventListeners() {
    // Send on Enter (but not Shift+Enter)
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Auto-resize textarea
    messageInput.addEventListener('input', autoResizeTextarea);

    // Enable/disable send button based on input
    messageInput.addEventListener('input', () => {
        sendButton.disabled = !messageInput.value.trim();
    });
}

function autoResizeTextarea() {
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
}

async function loadGreeting() {
    try {
        const response = await fetch(`${API_BASE}/greeting`);
        if (response.ok) {
            const data = await response.json();
            addMessage('assistant', data.greeting);
        } else {
            showWelcomeMessage();
        }
    } catch (error) {
        console.error('Failed to load greeting:', error);
        showWelcomeMessage();
    }
}

function showWelcomeMessage() {
    const welcome = document.createElement('div');
    welcome.className = 'welcome-message';
    welcome.innerHTML = `
        <div class="welcome-icon">✡️</div>
        <h2>Shalom and Welcome</h2>
        <p>I'm here to help you explore questions of Jewish thought, practice, and meaning from a progressive Modern Orthodox perspective. What's on your mind today?</p>
    `;
    chatMessages.appendChild(welcome);
}

async function sendMessage() {
    const message = messageInput.value.trim();
    if (!message || isLoading) return;

    // Clear input
    messageInput.value = '';
    autoResizeTextarea();
    sendButton.disabled = true;

    // Add user message to chat
    addMessage('user', message);

    // Show loading state
    setLoading(true);
    showTypingIndicator();

    try {
        const response = await fetch(`${API_BASE}/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                message: message,
                conversation_history: conversationHistory,
                session_id: sessionId,
            }),
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        // Update session ID
        sessionId = data.session_id;

        // Remove typing indicator
        removeTypingIndicator();

        // Add assistant response
        addMessage('assistant', data.response);

        // Show referral notice if needed
        if (data.requires_human_referral) {
            showReferralNotice();
        } else {
            hideReferralNotice();
        }

    } catch (error) {
        console.error('Error sending message:', error);
        removeTypingIndicator();
        addMessage('assistant',
            "I'm having trouble responding right now. Please try again in a moment. " +
            "If this continues, you might want to speak with a human rabbi who can give you their full attention."
        );
    } finally {
        setLoading(false);
    }
}

function addMessage(role, content) {
    // Remove welcome message if present
    const welcome = chatMessages.querySelector('.welcome-message');
    if (welcome) {
        welcome.remove();
    }

    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = role === 'user' ? '👤' : '📜';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.textContent = content;

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(contentDiv);

    chatMessages.appendChild(messageDiv);

    // Update conversation history
    conversationHistory.push({ role, content });

    // Keep only last 10 messages in history to manage context
    if (conversationHistory.length > 20) {
        conversationHistory = conversationHistory.slice(-20);
    }

    // Scroll to bottom
    scrollToBottom();
}

function showTypingIndicator() {
    const typing = document.createElement('div');
    typing.className = 'message assistant';
    typing.id = 'typingIndicator';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = '📜';

    const indicator = document.createElement('div');
    indicator.className = 'message-content typing-indicator';
    indicator.innerHTML = '<span></span><span></span><span></span>';

    typing.appendChild(avatar);
    typing.appendChild(indicator);

    chatMessages.appendChild(typing);
    scrollToBottom();
}

function removeTypingIndicator() {
    const typing = document.getElementById('typingIndicator');
    if (typing) {
        typing.remove();
    }
}

function setLoading(loading) {
    isLoading = loading;
    sendButton.disabled = loading || !messageInput.value.trim();

    // Don't show overlay - just use typing indicator
    // loadingOverlay.classList.toggle('hidden', !loading);
}

function showReferralNotice() {
    referralNotice.classList.remove('hidden');
}

function hideReferralNotice() {
    referralNotice.classList.add('hidden');
}

function dismissDisclaimer() {
    disclaimerBanner.classList.add('hidden');
    localStorage.setItem('disclaimerDismissed', 'true');
}

function scrollToBottom() {
    const container = document.getElementById('chatContainer');
    setTimeout(() => {
        container.scrollTop = container.scrollHeight;
    }, 100);
}

// Expose dismissDisclaimer to global scope for onclick
window.dismissDisclaimer = dismissDisclaimer;
window.sendMessage = sendMessage;
