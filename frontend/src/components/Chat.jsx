import React, { useState, useRef, useEffect, useCallback } from 'react';
import './Chat.css';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

function generateSessionId() {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let id = 's-';
  for (let i = 0; i < 8; i++) {
    id += chars[Math.floor(Math.random() * chars.length)];
  }
  return id;
}

function Chat() {
  const [sessionId] = useState(() => generateSessionId());
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const sendMessage = async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;

    const userMsg = { role: 'user', content: trimmed };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const body = { session_id: sessionId, message: trimmed };
      if (systemPrompt.trim()) {
        body.system_prompt = systemPrompt.trim();
      }

      const resp = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const data = await resp.json();

      if (!resp.ok) {
        const detail = data.detail
          ? (Array.isArray(data.detail) ? data.detail.join('; ') : data.detail)
          : `Error ${resp.status}`;
        const errMsg = resp.status === 422
          ? `⚠️ Invalid input: ${detail}`
          : `❌ ${detail}`;
        setMessages(prev => [...prev, { role: 'error', content: errMsg }]);
      } else {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: data.reply,
          metadata: data.metadata,
        }]);
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'error',
        content: `❌ Network error: ${err.message}`,
      }]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="chat-container">
      {/* System prompt */}
      <div className="system-prompt-bar">
        <input
          data-testid="system-prompt-input"
          type="text"
          className="system-prompt-field"
          placeholder="System prompt (optional) — sets behavior for this session"
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
        />
      </div>

      {/* Messages */}
      <div className="messages-area">
        {messages.length === 0 && (
          <div className="empty-state">
            <span className="empty-icon">💬</span>
            <p>Start a conversation</p>
            <span className="session-badge">Session: {sessionId}</span>
          </div>
        )}
        {messages.map((msg, idx) => (
          <div key={idx} className={`message message-${msg.role}`}>
            {msg.role === 'user' && (
              <div className="message-bubble user-bubble">
                <p>{msg.content}</p>
              </div>
            )}
            {msg.role === 'assistant' && (
              <div className="message-bubble assistant-bubble" data-testid="assistant-message">
                <p className="reply-text">{msg.content}</p>
                {msg.metadata && (
                  <div className="metadata-row">
                    <span
                      className={`badge ${msg.metadata.resolution_source === 'LLM_CACHE' ? 'badge-cache' : 'badge-live'}`}
                      data-testid="meta-source"
                    >
                      {msg.metadata.resolution_source}
                    </span>
                    <span className="meta-item" data-testid="meta-model">
                      {msg.metadata.model}
                    </span>
                    <span className="meta-item" data-testid="meta-latency">
                      {msg.metadata.latency_ms} ms
                    </span>
                    <span className="meta-item" data-testid="meta-input-tokens">
                      {msg.metadata.input_tokens}
                    </span>
                    <span className="meta-item" data-testid="meta-output-tokens">
                      {msg.metadata.output_tokens}
                    </span>
                    {msg.metadata.key_id && (
                      <span className="badge badge-key">
                        {msg.metadata.key_id}
                      </span>
                    )}
                    {msg.metadata.fallback_attempts > 0 && (
                      <span className="badge badge-fallback">
                        {msg.metadata.fallback_attempts} fallback{msg.metadata.fallback_attempts > 1 ? 's' : ''}
                      </span>
                    )}
                  </div>
                )}
              </div>
            )}
            {msg.role === 'error' && (
              <div className="message-bubble error-bubble">
                <p>{msg.content}</p>
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="message message-assistant">
            <div className="message-bubble assistant-bubble loading-bubble">
              <div className="typing-indicator">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="input-area">
        <div className="input-row">
          <textarea
            data-testid="chat-input"
            className="chat-input"
            placeholder="Type a message..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            disabled={loading}
          />
          <button
            data-testid="send-button"
            className="send-button"
            onClick={sendMessage}
            disabled={loading || !input.trim()}
          >
            {loading ? '...' : '➤'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default Chat;
