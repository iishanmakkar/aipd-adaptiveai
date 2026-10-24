/** Caregiver / helper view: POST /api/share gives a read-only link, this is the
 * page that link opens. It shows the same transcript the user is seeing, and
 * whatever the helper writes here arrives in the user's chat as a note they
 * hear - so a parent or support worker can guide without touching their device.
 *
 * The token in the URL is the only credential, so this view asks for no login
 * and can never write to the session: the backend returns `read_only` and
 * exposes no mutation route besides an annotation.
 */
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { apiService } from '../services/api';
import { enqueueSpeech } from '../utils/speechQueue';
import type { SharedSessionResponse } from '../types/api';

const POLL_MS = 8000;

export function SharedSession({ token }: { token: string }) {
  const [data, setData] = useState<SharedSessionResponse | null>(null);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [sending, setSending] = useState(false);
  const seen = useRef<{ messages: number; annotations: number } | null>(null);

  useEffect(() => {
    let stopped = false;

    async function poll() {
      try {
        const next = await apiService.watchShare(token);
        if (stopped) return;
        const previous = seen.current;
        if (previous && next.messages.length > previous.messages) {
          const latest = next.messages[next.messages.length - 1];
          // The list can be empty between polls (session reset server-side):
          // announcing latest.role of undefined crashed this view.
          if (latest) {
            // The helper is told what just happened on the user's screen without
            // having to watch for it.
            void enqueueSpeech(
              `New ${latest.role === 'user' ? 'question' : 'answer'}: ${latest.content}`);
          }
        }
        seen.current = { messages: next.messages.length, annotations: next.annotations.length };
        setData(next);
        setError('');
      } catch (err) {
        if (stopped) return;
        const status = (err as { response?: { status?: number } }).response?.status;
        if (status === 404) {
          // Expired (the normal 24h end of life) or never valid: polling a
          // permanently-dead route every 8s used to run FOREVER - hundreds
          // of dead requests from a forgotten tab. Stop; a new link remounts
          // this component with a new token.
          setError('This share link has expired or was never valid. Ask the user to create a new one.');
          stopped = true;
          window.clearInterval(timer);
          return;
        }
        setError('Cannot reach AdaptiveAI right now - retrying.');
        seen.current = seen.current ?? { messages: 0, annotations: 0 };
      }
    }

    poll();
    const timer = window.setInterval(poll, POLL_MS);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [token]);

  async function send(event: FormEvent) {
    event.preventDefault();
    const text = note.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      await apiService.annotateShare(token, text);
      setNote('');
    } catch {
      setError('Your note could not be sent. Try again.');
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <a className="skip-link" href="#main-content">Skip to the conversation</a>
      <main className="shared-shell" id="main-content" tabIndex={-1} aria-labelledby="shared-title">
      <header className="shared-header">
        <h1 id="shared-title">AdaptiveAI - shared session</h1>
        <p className="shared-badge">Read-only view · your notes are spoken to the user</p>
      </header>

      {error && <p className="shared-error" role="alert">{error}</p>}

      <section className="shared-transcript" aria-label="Conversation" role="log">
        {!data && !error && <p>Loading the session…</p>}
        {data?.messages.map((message, index) => (
          <article key={index} className={`shared-message shared-${message.role}`}>
            <h2>{message.role === 'user' ? 'User' : 'AdaptiveAI'}</h2>
            <p>{message.content}</p>
          </article>
        ))}
        {data && data.messages.length === 0 && <p>No messages in this session yet.</p>}
      </section>

      {data && data.annotations.length > 0 && (
        <section className="shared-notes" aria-label="Notes you have sent">
          <h2>Notes sent ({data.annotations.length})</h2>
          <ul>
            {data.annotations.map((annotation, index) => (
              <li key={index}>{annotation.text}</li>
            ))}
          </ul>
        </section>
      )}

      <form className="shared-note-form" onSubmit={send}>
        <label htmlFor="shared-note">Tell the user something (they will hear it)</label>
        <div className="shared-note-row">
          <input
            id="shared-note"
            type="text"
            maxLength={2000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. Press the Book tickets button at the bottom now"
          />
          <button type="submit" disabled={sending || !note.trim()}>
            {sending ? 'Sending…' : 'Send note'}
          </button>
        </div>
      </form>
    </main>
    </>
  );
}
