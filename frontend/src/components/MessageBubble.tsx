import { useMemo, useState } from 'react';
import type { Message } from '../types/chat';
import { renderMarkdown } from '../utils/markdown';

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const [copied, setCopied] = useState(false);

  const timeString = useMemo(() => {
    return message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }, [message.timestamp]);

  const getAriaLabel = () => {
    if (message.is_loading) return 'Loading response';
    if (message.role === 'user') return `You said: ${message.content}`;
    return `Assistant: ${message.content}`;
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard unavailable (permissions/insecure context) - quietly ignore
    }
  };

  return (
    <div
      className={`message-bubble ${isUser ? 'user' : 'assistant'} ${message.is_loading ? 'loading' : ''}`}
      role="article"
      aria-label={getAriaLabel()}
      aria-live={message.role === 'assistant' && !message.is_loading ? 'polite' : 'off'}
    >
      <div className="message-content">
        {message.is_loading ? (
          <span className="loading-text" aria-hidden="true">Thinking…</span>
        ) : isUser ? (
          <p className="message-text">{message.content}</p>
        ) : (
          <div className="message-text md-body">{renderMarkdown(message.content)}</div>
        )}
      </div>

      <div className="message-meta">
        <time className="message-time" dateTime={message.timestamp.toISOString()}>
          {timeString}
        </time>

        {!isUser && message.agent_used && (
          <span className="agent-badge" aria-label={`Handled by ${message.agent_used}`}>
            {message.agent_used}
          </span>
        )}

        {!isUser && message.confidence !== undefined && (
          <span className="confidence-badge" aria-label={`Confidence ${Math.round(message.confidence * 100)}%`}>
            {Math.round(message.confidence * 100)}%
          </span>
        )}

        {message.input_source === 'voice' && (
          <span className="voice-badge" aria-label="Voice input">
            🎤
          </span>
        )}

        {!isUser && !message.is_loading && message.content && (
          <button
            type="button"
            className="copy-button"
            onClick={handleCopy}
            aria-label={copied ? 'Answer copied' : 'Copy answer to clipboard'}
          >
            {copied ? '✓ Copied' : 'Copy'}
          </button>
        )}
      </div>

      {!isUser && message.sources && message.sources.length > 0 && (
        <div className="message-sources" aria-label="Knowledge sources used">
          <span className="sources-label" aria-hidden="true">Sources:</span>
          {message.sources.map((source) => (
            <span key={source} className="source-chip">{source}</span>
          ))}
        </div>
      )}

      {message.suggested_action && message.suggested_action !== 'none' && (
        <div className="suggested-action" role="status" aria-live="polite">
          <span className="action-icon" aria-hidden="true">💡</span>
          <span>Suggested: {message.suggested_action.replace('_', ' ')}</span>
        </div>
      )}
    </div>
  );
}