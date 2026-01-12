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
    sidebarUserName.textContent = fullName;

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
        sidebarDropdown.classList.toggle('hidden');
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', () => {
        sidebarDropdown.classList.add('hidden');
        document.querySelectorAll('.conversation-dropdown').forEach(d => d.classList.add('hidden'));
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
                addMessageToUI(msg.role, msg.content, new Date(msg.created_at));
            });

            // Update title
            chatTitle.textContent = data.title || 'New conversation';

            // Switch to chat screen
            welcomeScreen.classList.add('hidden');
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
            finalizeStreamingMessage(messageElement, fullResponse);
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

function addMessageToUI(role, content, date) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

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

function finalizeStreamingMessage(messageElement, content) {
    const contentDiv = messageElement.querySelector('.message-content');
    contentDiv.innerHTML = formatMarkdown(content);
    contentDiv.classList.remove('streaming');
    messageElement.removeAttribute('id');

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
    indicator.innerHTML = `
        <div class="thinking-phase">
            <span class="phase-text">${agentPhases[0].phrase}</span>
            <div class="phase-dots"><span></span><span></span><span></span></div>
        </div>
    `;

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
