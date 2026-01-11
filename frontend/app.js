/**
 * rebbe.dev - Modern Frontend Application
 */

// Configuration
const API_BASE = '/api';

// State
let conversationHistory = [];
let sessionId = null;
let isLoading = false;
let currentUser = null;

// DOM Elements
const welcomeScreen = document.getElementById('welcomeScreen');
const chatScreen = document.getElementById('chatScreen');
const greetingText = document.getElementById('greetingText');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const chatInput = document.getElementById('chatInput');
const chatSendBtn = document.getElementById('chatSendBtn');
const chatMessages = document.getElementById('chatMessages');
const backBtn = document.getElementById('backBtn');
const referralNotice = document.getElementById('referralNotice');
const loadingIndicator = document.getElementById('loadingIndicator');
const suggestionChips = document.querySelectorAll('.suggestion-chip');

// User menu elements
const welcomeUserBtn = document.getElementById('welcomeUserBtn');
const welcomeDropdown = document.getElementById('welcomeDropdown');
const welcomeUserAvatar = document.getElementById('welcomeUserAvatar');
const welcomeUserName = document.getElementById('welcomeUserName');
const welcomeUserEmail = document.getElementById('welcomeUserEmail');
const welcomeEditAccount = document.getElementById('welcomeEditAccount');

const chatUserBtn = document.getElementById('chatUserBtn');
const chatDropdown = document.getElementById('chatDropdown');
const chatUserAvatar = document.getElementById('chatUserAvatar');
const chatUserName = document.getElementById('chatUserName');
const chatUserEmail = document.getElementById('chatUserEmail');
const chatEditAccount = document.getElementById('chatEditAccount');

// Initialize
document.addEventListener('DOMContentLoaded', init);

async function init() {
    // Check authentication first
    const isAuthenticated = await checkAuth();

    // Always setup event listeners (some work when logged out)
    setupEventListeners();

    if (!isAuthenticated) {
        // Show logged-out state in UI
        showLoggedOutState();
        return;
    }

    await loadGreeting();
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

    // Update welcome screen
    welcomeUserAvatar.textContent = initials;
    welcomeUserName.textContent = fullName;
    welcomeUserEmail.textContent = email;

    // Update chat screen
    chatUserAvatar.textContent = initials;
    chatUserName.textContent = fullName;
    chatUserEmail.textContent = email;

    // Hide login prompt if shown
    hideLoginPrompt();
}

function showLoggedOutState() {
    // Update avatars to show login icon
    welcomeUserAvatar.innerHTML = '&#x2192;'; // Arrow icon
    welcomeUserAvatar.style.fontSize = '1.2rem';
    chatUserAvatar.innerHTML = '&#x2192;';
    chatUserAvatar.style.fontSize = '1.2rem';

    // Update dropdowns to show login option
    const loginDropdownContent = `
        <div class="user-info">
            <span class="user-name">Not signed in</span>
            <span class="user-email">Sign in to chat</span>
        </div>
        <div class="dropdown-divider"></div>
        <a href="/auth/login" class="dropdown-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>
                <polyline points="10 17 15 12 10 7"/>
                <line x1="15" y1="12" x2="3" y2="12"/>
            </svg>
            Sign In
        </a>
    `;
    welcomeDropdown.innerHTML = loginDropdownContent;
    chatDropdown.innerHTML = loginDropdownContent;
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

function toggleDropdown(dropdown) {
    const isHidden = dropdown.classList.contains('hidden');
    // Close all dropdowns first
    welcomeDropdown.classList.add('hidden');
    chatDropdown.classList.add('hidden');
    // Toggle the clicked one
    if (isHidden) {
        dropdown.classList.remove('hidden');
    }
}

function closeAllDropdowns() {
    welcomeDropdown.classList.add('hidden');
    chatDropdown.classList.add('hidden');
}

function logout() {
    window.location.href = '/auth/logout';
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

    // Back button
    backBtn.addEventListener('click', startNewConversation);

    // User menu dropdowns
    welcomeUserBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleDropdown(welcomeDropdown);
    });
    chatUserBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleDropdown(chatDropdown);
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', closeAllDropdowns);

    // Prevent dropdown from closing when clicking inside
    welcomeDropdown.addEventListener('click', (e) => e.stopPropagation());
    chatDropdown.addEventListener('click', (e) => e.stopPropagation());

    // Edit account (placeholder - opens WorkOS account portal if available)
    welcomeEditAccount.addEventListener('click', (e) => {
        e.preventDefault();
        alert('Account settings coming soon. Contact your administrator for account changes.');
    });
    chatEditAccount.addEventListener('click', (e) => {
        e.preventDefault();
        alert('Account settings coming soon. Contact your administrator for account changes.');
    });

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
            // Extract a shorter greeting for the welcome screen
            const greeting = data.greeting || 'Shalom';
            // Just use "Shalom" for the welcome screen title
            greetingText.textContent = 'Shalom, how can I help?';
        }
    } catch (error) {
        console.error('Failed to load greeting:', error);
        greetingText.textContent = 'Shalom, how can I help?';
    }
}

function sendFromWelcome() {
    const message = messageInput.value.trim();
    if (!message || isLoading) return;

    // Switch to chat screen
    welcomeScreen.classList.add('hidden');
    chatScreen.classList.remove('hidden');

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

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            // Keep the last incomplete line in buffer
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));

                        if (data.type === 'session') {
                            sessionId = data.session_id;
                        } else if (data.type === 'metadata') {
                            requiresHumanReferral = data.data.requires_human_referral;
                        } else if (data.type === 'token') {
                            // Create streaming message on first token
                            if (!messageElement) {
                                removeTypingIndicator();
                                messageElement = createStreamingMessage();
                            }
                            fullResponse += data.data;
                            updateStreamingMessage(messageElement, fullResponse);
                        } else if (data.type === 'error') {
                            throw new Error(data.message);
                        }
                    } catch (e) {
                        console.error('Error parsing SSE:', e, line);
                    }
                }
            }
        }

        // Finalize the message (only if we received tokens)
        if (messageElement) {
            finalizeStreamingMessage(messageElement, fullResponse);
        } else {
            // No tokens received - show error
            removeTypingIndicator();
            throw new Error('No response received');
        }

        // Show referral notice if needed
        if (requiresHumanReferral) {
            showReferralNotice();
        } else {
            hideReferralNotice();
        }

    } catch (error) {
        console.error('Error sending message:', error);
        removeTypingIndicator();
        // Remove any partially created streaming message
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
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    // Format markdown for assistant messages, plain text for user
    if (role === 'assistant') {
        contentDiv.innerHTML = formatMarkdown(content);
    } else {
        contentDiv.textContent = content;
    }

    const metaDiv = document.createElement('div');
    metaDiv.className = 'message-meta';

    const timeSpan = document.createElement('span');
    timeSpan.className = 'message-time';
    timeSpan.textContent = formatTime(new Date());

    metaDiv.appendChild(timeSpan);

    messageDiv.appendChild(contentDiv);
    messageDiv.appendChild(metaDiv);

    chatMessages.appendChild(messageDiv);

    // Update conversation history
    conversationHistory.push({ role, content });

    // Keep only last 20 messages in history
    if (conversationHistory.length > 20) {
        conversationHistory = conversationHistory.slice(-20);
    }

    // Scroll to bottom
    scrollToBottom();
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
    // Escape HTML first to prevent XSS
    let html = escapeHtml(text);
    // Bold: **text**
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italics: *text*
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

function finalizeStreamingMessage(messageElement, content) {
    const contentDiv = messageElement.querySelector('.message-content');
    contentDiv.innerHTML = formatMarkdown(content);
    contentDiv.classList.remove('streaming');
    messageElement.removeAttribute('id');

    // Update conversation history
    conversationHistory.push({ role: 'assistant', content });

    // Keep only last 20 messages in history
    if (conversationHistory.length > 20) {
        conversationHistory = conversationHistory.slice(-20);
    }
}

// Agent phases with clever phrases
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
    indicator.innerHTML = `
        <div class="thinking-phase">
            <span class="phase-text">${agentPhases[0].phrase}</span>
            <div class="phase-dots"><span></span><span></span><span></span></div>
        </div>
    `;

    typing.appendChild(indicator);
    chatMessages.appendChild(typing);
    scrollToBottom();

    // Start cycling through phases
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
    // Clear the phase cycling interval
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

    // Clear messages
    chatMessages.innerHTML = '';

    // Hide referral notice
    hideReferralNotice();

    // Switch to welcome screen
    chatScreen.classList.add('hidden');
    welcomeScreen.classList.remove('hidden');

    // Reset inputs
    messageInput.value = '';
    chatInput.value = '';
    sendBtn.disabled = true;
    chatSendBtn.disabled = true;

    // Focus welcome input
    setTimeout(() => messageInput.focus(), 300);
}

function scrollToBottom() {
    setTimeout(() => {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }, 100);
}
