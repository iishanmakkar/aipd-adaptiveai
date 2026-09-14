import { useEffect } from 'react';
import type { SessionSummary } from '../types/api';

interface HistoryPanelProps {
  open: boolean;
  onClose: () => void;
  sessions: SessionSummary[];
  currentSessionId: string;
  loading: boolean;
  onSelect: (sessionId: string) => void;
  onRefresh: () => void;
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  return sameDay
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

/**
 * Slide-over list of the user's previous sessions. Requires the backend
 * (GET /api/sessions); in demo mode it shows an explanatory empty state.
 */
export function HistoryPanel({
  open, onClose, sessions, currentSessionId, loading, onSelect, onRefresh,
}: HistoryPanelProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div className="history-backdrop" onClick={onClose} aria-hidden="true" />
      <aside
        className="history-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Session history"
      >
        <div className="history-header">
          <h2 className="history-title">History</h2>
          <div className="history-header-actions">
            <button
              type="button"
              className="header-button"
              onClick={onRefresh}
              aria-label="Refresh session list"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M21 12v5h-5" />
              </svg>
            </button>
            <button
              type="button"
              className="header-button"
              onClick={onClose}
              aria-label="Close history"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>

        {loading ? (
          <p className="history-empty">Loading…</p>
        ) : sessions.length === 0 ? (
          <p className="history-empty">
            No previous sessions yet. Your conversations will appear here once you
            start asking questions.
          </p>
        ) : (
          <ul className="history-list">
            {sessions.map((session) => (
              <li key={session.session_id}>
                <button
                  type="button"
                  className={`history-item ${session.session_id === currentSessionId ? 'current' : ''}`}
                  onClick={() => { onSelect(session.session_id); onClose(); }}
                  aria-current={session.session_id === currentSessionId || undefined}
                >
                  <span className="history-item-when">{formatWhen(session.created_at)}</span>
                  <span className="history-item-count">
                    {session.message_count} {session.message_count === 1 ? 'message' : 'messages'}
                  </span>
                  {session.session_id === currentSessionId && (
                    <span className="history-current-badge">Current</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </>
  );
}
