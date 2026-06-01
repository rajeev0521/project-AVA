/**
 * AVA Frontend — Web Speech API + WebSocket Client
 * Handles voice input/output and API communication.
 */

// ── Configuration & Auth ─────────────────────────────────────────

const API_BASE = window.location.origin;
const WS_BASE = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;

// Check for auth parameters from OAuth callback redirect
const urlParams = new URLSearchParams(window.location.search);
if (urlParams.has('user_id')) {
    localStorage.setItem('ava_user_id', urlParams.get('user_id'));
    if (urlParams.has('name')) {
        localStorage.setItem('ava_user_name', urlParams.get('name'));
    }
    if (urlParams.has('picture')) {
        localStorage.setItem('ava_user_picture', urlParams.get('picture'));
    }
    // Clean URL
    window.history.replaceState({}, document.title, window.location.pathname);
}

const USER_ID = localStorage.getItem('ava_user_id');
let USERNAME = localStorage.getItem('ava_user_name') || "User";
const USER_PICTURE = localStorage.getItem('ava_user_picture');

// ── State ────────────────────────────────────────────────────────

let isListening = false;
let recognition = null;
let ws = null;
let isWsConnected = false;

// ── DOM Elements ─────────────────────────────────────────────────

const commandInput = document.getElementById('commandInput');
const conversation = document.getElementById('conversation');
const welcomeMessage = document.getElementById('welcomeMessage');
const micButton = document.getElementById('micButton');
const micIcon = document.getElementById('micIcon');
const micActiveIcon = document.getElementById('micActiveIcon');
const statusIndicator = document.getElementById('statusIndicator');
const connectionStatus = document.getElementById('connectionStatus');
const apiRemaining = document.getElementById('apiRemaining');

// ── Initialization ───────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    checkAuthState();
    if (USER_ID) {
        initWebSocket();
        initSpeechRecognition();
        initKeyboardShortcuts();
        fetchApiStats();
        
        // Refresh API stats every 30 seconds
        setInterval(fetchApiStats, 30000);
    }
});

function checkAuthState() {
    const loginScreen = document.getElementById('loginScreen');
    const mainApp = document.getElementById('mainApp');
    const userProfile = document.getElementById('userProfile');
    
    if (!USER_ID) {
        // Not logged in
        loginScreen.classList.remove('hidden');
        mainApp.classList.add('hidden');
        userProfile.classList.add('hidden');
    } else {
        // Logged in
        loginScreen.classList.add('hidden');
        mainApp.classList.remove('hidden');
        userProfile.classList.remove('hidden');
        
        // Populate user profile
        document.getElementById('userDisplayName').textContent = USERNAME;
        const avatar = document.getElementById('userAvatar');
        if (USER_PICTURE) {
            avatar.src = USER_PICTURE;
            avatar.classList.remove('hidden');
        }
    }
}

function logout() {
    localStorage.removeItem('ava_user_id');
    localStorage.removeItem('ava_user_name');
    localStorage.removeItem('ava_user_picture');
    window.location.href = '/auth/logout';
}

// ── WebSocket Connection ─────────────────────────────────────────

function initWebSocket() {
    try {
        ws = new WebSocket(`${WS_BASE}/ws/${USER_ID}`);
        
        ws.onopen = () => {
            isWsConnected = true;
            updateConnectionStatus(true);
            console.log('[AVA] WebSocket connected');
        };
        
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            handleResponse(data);
        };
        
        ws.onclose = () => {
            isWsConnected = false;
            updateConnectionStatus(false);
            console.log('[AVA] WebSocket disconnected. Reconnecting in 3s...');
            setTimeout(initWebSocket, 3000);
        };
        
        ws.onerror = (error) => {
            console.error('[AVA] WebSocket error:', error);
            isWsConnected = false;
            updateConnectionStatus(false);
        };
    } catch (e) {
        console.error('[AVA] WebSocket init failed:', e);
        updateConnectionStatus(false);
    }
}

function updateConnectionStatus(connected) {
    const badge = document.getElementById('connectionStatus');
    const dot = badge.querySelector('.status-dot');
    const text = badge.querySelector('.status-text');
    
    if (connected) {
        badge.classList.remove('disconnected');
        text.textContent = 'Connected';
    } else {
        badge.classList.add('disconnected');
        text.textContent = 'Reconnecting...';
    }
}

// ── Speech Recognition (Web Speech API) ──────────────────────────

function initSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    
    if (!SpeechRecognition) {
        console.warn('[AVA] Web Speech API not supported in this browser');
        micButton.title = 'Voice input not supported in this browser';
        micButton.style.opacity = '0.4';
        return;
    }
    
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-IN'; // English (India) — supports Hindi words too
    
    recognition.onresult = (event) => {
        const transcript = Array.from(event.results)
            .map(r => r[0].transcript)
            .join('');
        
        commandInput.value = transcript;
        
        // Send when final result
        if (event.results[event.results.length - 1].isFinal) {
            stopListening();
            if (transcript.trim()) {
                sendCommand();
            }
        }
    };
    
    recognition.onerror = (event) => {
        console.error('[AVA] Speech recognition error:', event.error);
        stopListening();
    };
    
    recognition.onend = () => {
        if (isListening) {
            stopListening();
        }
    };
}

function toggleVoice() {
    if (isListening) {
        stopListening();
    } else {
        startListening();
    }
}

function startListening() {
    if (!recognition) return;
    
    isListening = true;
    micButton.classList.add('active');
    micIcon.classList.add('hidden');
    micActiveIcon.classList.remove('hidden');
    statusIndicator.classList.add('listening');
    commandInput.placeholder = 'Listening...';
    
    try {
        recognition.start();
    } catch (e) {
        console.error('[AVA] Failed to start recognition:', e);
        stopListening();
    }
}

function stopListening() {
    isListening = false;
    micButton.classList.remove('active');
    micIcon.classList.remove('hidden');
    micActiveIcon.classList.add('hidden');
    statusIndicator.classList.remove('listening');
    commandInput.placeholder = 'Type a command or click the mic...';
    
    try {
        if (recognition) recognition.stop();
    } catch (e) {
        // Recognition may not be active; suppress stop errors gracefully
    }
}

// ── Text-to-Speech (Web Speech API) ──────────────────────────────

function speak(text) {
    if (!window.speechSynthesis) return;
    
    // Cancel any ongoing speech
    window.speechSynthesis.cancel();
    
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;
    
    // Try to use a natural-sounding voice
    const voices = window.speechSynthesis.getVoices();
    const preferredVoice = voices.find(v => 
        v.name.includes('Google') || 
        v.name.includes('Natural') || 
        v.name.includes('Samantha')
    ) || voices.find(v => v.lang.startsWith('en'));
    
    if (preferredVoice) {
        utterance.voice = preferredVoice;
    }
    
    window.speechSynthesis.speak(utterance);
}

// Ensure voices are loaded
window.speechSynthesis?.addEventListener('voiceschanged', () => {
    window.speechSynthesis.getVoices();
});

// ── Command Sending ──────────────────────────────────────────────

function sendCommand() {
    const text = commandInput.value.trim();
    if (!text) return;
    
    // Hide welcome message on first command
    if (welcomeMessage) {
        welcomeMessage.style.display = 'none';
    }
    
    // Add user message to conversation
    addMessage(text, 'user');
    commandInput.value = '';
    
    // Show typing indicator
    showTypingIndicator();
    
    // Send via WebSocket if connected, otherwise fall back to REST
    if (isWsConnected && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ text, user_name: USERNAME }));
    } else {
        sendViaRest(text);
    }
}

function sendQuickCommand(text) {
    commandInput.value = text;
    sendCommand();
}

async function sendViaRest(text) {
    try {
        const response = await fetch(`${API_BASE}/api/command`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, user_id: USER_ID, user_name: USERNAME }),
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Request failed');
        }
        
        const data = await response.json();
        handleResponse({
            type: 'response',
            intent: data.intent,
            response: data.response,
            action_result: data.action_result,
            used_local_classifier: data.used_local_classifier,
        });
    } catch (error) {
        hideTypingIndicator();
        addMessage(`Error: ${error.message}`, 'ava', { isError: true });
    }
}

// ── Response Handling ────────────────────────────────────────────

function handleResponse(data) {
    hideTypingIndicator();
    
    if (data.type === 'error') {
        addMessage(`⚠️ ${data.message}`, 'ava', { isError: true });
        return;
    }
    
    const meta = {};
    if (data.intent) meta.intent = data.intent;
    if (data.used_local_classifier) meta.local = true;
    
    addMessage(data.response, 'ava', meta);
    
    // Speak the response
    speak(data.response);
    
    // Update API stats
    fetchApiStats();
}

// ── UI Helpers ───────────────────────────────────────────────────

function addMessage(text, sender, meta = {}) {
    const messageEl = document.createElement('div');
    messageEl.className = `message ${sender}`;
    
    const avatarText = sender === 'user' ? '👤' : '✨';
    
    let metaHtml = '';
    if (meta.intent) {
        const localClass = meta.local ? ' local-badge' : '';
        metaHtml += `<span class="intent-badge${localClass}">${meta.intent}</span>`;
    }
    if (meta.local) {
        metaHtml += `<span class="intent-badge local-badge">⚡ LOCAL</span>`;
    }
    
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    
    messageEl.innerHTML = `
        <div class="message-avatar">${avatarText}</div>
        <div>
            <div class="message-content">${escapeHtml(text)}</div>
            <div class="message-meta">
                <span>${timeStr}</span>
                ${metaHtml}
            </div>
        </div>
    `;
    
    conversation.appendChild(messageEl);
    scrollToBottom();
}

function showTypingIndicator() {
    const existing = document.getElementById('typingIndicator');
    if (existing) return;
    
    const indicator = document.createElement('div');
    indicator.id = 'typingIndicator';
    indicator.className = 'message ava';
    indicator.innerHTML = `
        <div class="message-avatar">✨</div>
        <div class="message-content typing-indicator">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    `;
    
    conversation.appendChild(indicator);
    scrollToBottom();
}

function hideTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) indicator.remove();
}

function scrollToBottom() {
    conversation.scrollTop = conversation.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ── Keyboard Shortcuts ───────────────────────────────────────────

function initKeyboardShortcuts() {
    commandInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendCommand();
        }
    });
    
    document.addEventListener('keydown', (e) => {
        // Ctrl+M for mic toggle
        if (e.ctrlKey && e.key === 'm') {
            e.preventDefault();
            toggleVoice();
        }
        
        // Focus input on any typing
        if (!e.ctrlKey && !e.metaKey && !e.altKey && e.key.length === 1) {
            if (document.activeElement !== commandInput) {
                commandInput.focus();
            }
        }
    });
}

// ── API Stats ────────────────────────────────────────────────────

async function fetchApiStats() {
    try {
        const response = await fetch(`${API_BASE}/api/stats`);
        if (response.ok) {
            const data = await response.json();
            apiRemaining.textContent = data.daily_api_remaining || '--';
        }
    } catch (e) {
        // Silently fail — stats are non-critical
    }
}
