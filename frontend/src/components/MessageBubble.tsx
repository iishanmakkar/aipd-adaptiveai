import { useMemo, useState } from 'react';
import { apiService } from '../services/api';
import type { Message } from '../types/chat';
import { renderMarkdown } from '../utils/markdown';

interface MessageBubbleProps {
  message: Message;
  onReplay?: (content: string) => void;
}

export function MessageBubble({ message, onReplay }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const [copied, setCopied] = useState(false);
  const [braille, setBraille] = useState<string[] | null>(null);
  const [grade1, setGrade1] = useState<string[] | null>(null);
  const [brailleError, setBrailleError] = useState('');

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
          // The percentage alone implied a model judged it. When the number came
          // from the keyword fallback, say so - a 70% guess and a 70% judgment
          // are not the same claim, and a user who cannot see the badge only
          // gets what this label tells them.
          <span
            className="confidence-badge"
            aria-label={`Confidence ${Math.round(message.confidence * 100)}%${
              message.confidence_source === 'keyword'
                ? ', estimated by keyword match, not judged by the model'
                : message.confidence_source === 'default'
                  ? ', nothing matched, treated as uncertain'
                  : ''
            }`}
          >
            {Math.round(message.confidence * 100)}%
            {message.confidence_source === 'keyword' ? ' (keyword match)' : ''}
            {message.confidence_source === 'default' ? ' (no match)' : ''}
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

        {!isUser && !message.is_loading && message.content && onReplay && (
          <button
            type="button"
            className="copy-button replay-button"
            onClick={() => onReplay(message.content)}
            aria-label="Listen to this answer again"
          >
            🔊 Replay
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
        // Deliberately NOT a live region: this bubble already arrives inside the
        // conversation's aria-live=log container, and a nested polite region
        // makes a screen reader say the same answer two or three times over.
        <div className="suggested-action">
          <span className="action-icon" aria-hidden="true">💡</span>
          <span>Suggested: {message.suggested_action.replace(/_/g, ' ')}</span>
        </div>
      )}

      {!isUser && !message.is_loading && message.content && message.content.length > 0 && (
        <details className="alt-formats" onToggle={(event) => {
          // Fetch once: every re-open re-fetched and re-rendered over good
          // data (with the spinner flashing back over it on slow networks).
          if (event.currentTarget.open && braille === null && grade1 === null && !brailleError) {
            void loadBraille(message.content, setBraille, setGrade1, setBrailleError);
          }
        }}>
          <summary>Alternative formats (braille)</summary>
          <div className="alt-format-body">
            <section className="alt-format-block">
              <h3>For a refreshable display (shaped text)</h3>
              {braille === null && !brailleError && <p role="status">Shaping this answer for a braille display…</p>}
              {braille && braille.map((line, index) => (
                <pre key={index} className="braille-line" tabIndex={0} aria-label={`Display line ${index + 1} of ${braille.length}`}>
                  <span aria-hidden="true">{line}</span>
                  <span className="visually-hidden">{line}</span>
                </pre>
              ))}
            </section>
            <section className="alt-format-block">
              <h3>Grade-1 braille (uncontracted Unicode cells)</h3>
              {grade1 === null && !brailleError && <p role="status">Translating to Grade-1 braille…</p>}
              {grade1 && grade1.map((line, index) => (
                <pre key={index} className="braille-line" tabIndex={0} aria-label={`Grade-1 braille line ${index + 1} of ${grade1.length}`}>
                  <span aria-hidden="true">{line}</span>
                </pre>
              ))}
              <p className="alt-format-note" aria-description="Uncontracted braille cells; best on a refreshable display. Screen-reader users use Shaped text above.">
                Uncontracted Grade 1: every letter and number is spelled out cell by cell.
                It is not Grade-2 contracted braille.
              </p>
              {message.content.length > 4000 && (
                <p role="note">Showing braille for first 4000 characters.</p>
              )}
              {grade1 && grade1.length > 0 && (
                <p className="alt-format-note">
                  Uncontracted Grade 1: every letter and number is spelled out cell by cell.
                  It is not Grade-2 contracted braille.
                </p>
              )}
            </section>
            {brailleError && <p className="alt-format-error" role="alert">{brailleError}</p>}
          </div>
        </details>
      )}
    </div>
  );
}

/** Braille shaping and Grade-1 translation are server-side transformations of
 * the real answer text (GET /api/alt/braille), fetched the first time the
 * panel is opened rather than for every bubble on every render. */
async function loadBraille(
  content: string,
  setLines: (lines: string[]) => void,
  setGrade1Lines: (lines: string[]) => void,
  setError: (message: string) => void,
): Promise<void> {
  if (content.length === 0) return;
  try {
    const result = await apiService.braille(content.slice(0, 4000));
    setLines(result.lines.length ? result.lines : [result.preview_braille]);
    setGrade1Lines(result.grade1 ?? []);
  } catch {
    setError('The braille formatter is not reachable right now. The text answer above is unaffected.');
  }
}