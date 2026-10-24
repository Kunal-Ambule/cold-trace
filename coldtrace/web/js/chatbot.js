/**
 * ColdBot — AI chatbot widget for ColdTrace.
 * Attaches to the DOM after login and connects to /api/chat.
 */
(function () {
  'use strict';

  // ── State ────────────────────────────────────────────────────────────────
  let history = [];   // [{role, content}]
  let open    = false;
  let busy    = false;

  // ── Build DOM ─────────────────────────────────────────────────────────────
  function mount() {
    if (document.getElementById('cb-root')) return;

    const root = document.createElement('div');
    root.id = 'cb-root';
    root.innerHTML = `
      <button id="cb-fab" aria-label="Open ColdBot" title="Ask ColdBot">
        <span class="cb-fab-icon">🤖</span>
        <span class="cb-fab-label">ColdBot</span>
        <span id="cb-unread" class="cb-badge" hidden></span>
      </button>
      <div id="cb-panel" aria-live="polite" aria-label="ColdBot chat" hidden>
        <div id="cb-header">
          <div class="cb-header-left">
            <span class="cb-avatar">🤖</span>
            <div>
              <div class="cb-title">ColdBot</div>
              <div class="cb-subtitle">AI assistant · ColdTrace</div>
            </div>
          </div>
          <div class="cb-header-actions">
            <button id="cb-clear" class="cb-icon-btn" title="Clear conversation">🗑</button>
            <button id="cb-close" class="cb-icon-btn" title="Close">✕</button>
          </div>
        </div>
        <div id="cb-messages"></div>
        <div id="cb-typing" hidden>
          <span class="cb-dot"></span><span class="cb-dot"></span><span class="cb-dot"></span>
        </div>
        <div id="cb-input-row">
          <textarea id="cb-input" rows="1" placeholder="Ask about shipments, alerts, ML…" maxlength="800"></textarea>
          <button id="cb-send" class="cb-send-btn" title="Send" disabled>
            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
              <path d="M2.94 17.5l15.56-7.5L2.94 2.5 2 8.17l10 1.83-10 1.83z"/>
            </svg>
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(root);

    // Wire up events
    document.getElementById('cb-fab').addEventListener('click', togglePanel);
    document.getElementById('cb-close').addEventListener('click', (e) => {
      e.stopPropagation();
      closePanel();
    });
    document.getElementById('cb-clear').addEventListener('click', clearChat);
    document.getElementById('cb-send').addEventListener('click', sendMessage);

    const input = document.getElementById('cb-input');
    input.addEventListener('input', onInputChange);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });

    // Greet the user when they first open the panel
    addMessage('model', "Hi! I'm **ColdBot**, your ColdTrace AI assistant 🧊\n\nAsk me anything about the fleet, shipments, disputes, market prices, or how the AI works.");
  }

  // ── Panel open/close ──────────────────────────────────────────────────────
  function togglePanel() {
    open ? closePanel() : openPanel();
  }

  function openPanel() {
    open = true;
    const panel = document.getElementById('cb-panel');
    panel.hidden = false;
    panel.style.display = 'flex';
    document.getElementById('cb-fab').classList.add('cb-fab--open');
    document.getElementById('cb-unread').hidden = true;
    setTimeout(() => document.getElementById('cb-input').focus(), 60);
  }

  function closePanel() {
    open = false;
    const panel = document.getElementById('cb-panel');
    panel.hidden = true;
    panel.style.display = 'none';
    document.getElementById('cb-fab').classList.remove('cb-fab--open');
  }

  // ── Messages ──────────────────────────────────────────────────────────────
  function addMessage(role, text) {
    history.push({ role, content: text });
    const box = document.getElementById('cb-messages');
    const wrap = document.createElement('div');
    wrap.className = 'cb-msg cb-msg--' + role;

    const bubble = document.createElement('div');
    bubble.className = 'cb-bubble';
    bubble.innerHTML = renderMarkdown(text);
    wrap.appendChild(bubble);
    box.appendChild(wrap);
    box.scrollTop = box.scrollHeight;

    if (!open && role === 'model') {
      showUnread();
    }
  }

  function showUnread() {
    const badge = document.getElementById('cb-unread');
    badge.hidden = false;
  }

  function clearChat() {
    history = [];
    document.getElementById('cb-messages').innerHTML = '';
    addMessage('model', "Conversation cleared! How can I help you?");
  }

  // ── Lightweight markdown renderer ─────────────────────────────────────────
  function renderMarkdown(text) {
    return text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      // Bold
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      // Italic
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      // Inline code
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      // Bullets
      .replace(/^[•\-] (.+)/gm, '<li>$1</li>')
      // Numbered list
      .replace(/^\d+\. (.+)/gm, '<li>$1</li>')
      // Newlines → <br>
      .replace(/\n/g, '<br>');
  }

  // ── Send ──────────────────────────────────────────────────────────────────
  async function sendMessage() {
    if (busy) return;
    const input = document.getElementById('cb-input');
    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    onInputChange();
    addMessage('user', text);
    setTyping(true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: history.slice(-20)   // send last 20 turns to avoid huge payloads
        }),
      });
      const data = await res.json();
      if (data.error) {
        addMessage('model', `⚠️ ${data.error}`);
      } else {
        addMessage('model', data.reply || '_(empty response)_');
      }
    } catch (err) {
      addMessage('model', `⚠️ Network error: ${err.message}`);
    } finally {
      setTyping(false);
    }
  }

  function setTyping(on) {
    busy = on;
    document.getElementById('cb-typing').hidden = !on;
    document.getElementById('cb-send').disabled = on;
    if (!on) {
      const box = document.getElementById('cb-messages');
      box.scrollTop = box.scrollHeight;
    }
  }

  function onInputChange() {
    const val = document.getElementById('cb-input').value.trim();
    document.getElementById('cb-send').disabled = !val || busy;
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────
  // Mount when #app becomes visible (i.e. after login)
  const observer = new MutationObserver(() => {
    const app = document.getElementById('app');
    if (app && !app.hidden && getComputedStyle(app).display !== 'none') {
      mount();
    }
  });

  document.addEventListener('DOMContentLoaded', () => {
    observer.observe(document.body, { attributes: true, childList: true, subtree: true });
    // Also mount if already logged in
    const app = document.getElementById('app');
    if (app && !app.hidden) mount();
  });
})();
