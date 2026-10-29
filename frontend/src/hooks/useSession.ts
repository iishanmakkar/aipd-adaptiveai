import { useState, useCallback, useEffect, useRef } from 'react';
import { getOrCreateSessionId, storeSessionId, generateSessionId } from '../utils/session';
import { apiService } from '../services/api';
import type { Message } from '../types/chat';
import type { HistoryMessage, HistoryResponse, SessionSummary } from '../types/api';

/** Map a history API row onto the UI Message shape: `created_at` is an ISO
 * string on the wire, but MessageBubble calls Date methods on `timestamp`, and
 * feeding it the raw string crashed the whole chat on reload. */
function normalizeMessage(m: HistoryMessage): Message {
  const t = new Date(m.created_at);
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    timestamp: Number.isNaN(+t) ? new Date() : t,
    agent_used: m.agent_used ?? undefined,
  };
}

/** History is paginated server-side and ordered oldest-first, so page 1 is
 * the OLDEST messages. A conversation longer than one page restored only its
 * first 20 rows and the caregiver-note poll could never see past them —
 * always fetch the LAST page instead. */
async function fetchLatestHistory(sessionId: string) {
  const first: HistoryResponse = await apiService.getHistory(sessionId);
  const lastPage = Math.max(1, Math.ceil(first.total / Math.max(1, first.page_size)));
  if (lastPage > first.page) {
    return apiService.getHistory(sessionId, lastPage, first.page_size);
  }
  return first;
}

export function useSession() {
  const [sessionId, setSessionId] = useState<string>(() => getOrCreateSessionId());
  const [history, setHistory] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [sessionReady, setSessionReady] = useState(false);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);

  /**
   * The session id lives in localStorage, but the backend only accepts queries
   * for sessions created via POST /api/session - a fresh browser therefore got
   * 404 on every /api/query and the app apologised out loud to the user.
   * Bootstrap closes that gap: restore history if the session exists, and
   * create it server-side when it does not.
   */
  // Mirror of sessionId for async guards: a slow bootstrap for session A that
  // resolves after the user switched to B must not write A's rows (the old
  // code did exactly that, then B's own bootstrap discarded B's history).
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;
  // Latest history for computing poll additions outside setState updaters
  // (React may run updaters later/double - reading the result synchronously
  // after setHistory always saw []).
  const historyRef = useRef<Message[]>([]);
  useEffect(() => {
    historyRef.current = history;
  }, [history]);
  const pollRemoteBusyRef = useRef(false);

  const bootstrap = useCallback(async () => {
    const forSession = sessionIdRef.current;
    setIsLoading(true);
    setSessionReady(false);
    try {
      const response = await fetchLatestHistory(forSession);
      if (sessionIdRef.current !== forSession) return;
      // Never wipe what is already on screen: a restore that races user
      // activity (or StrictMode's second pass) must not delete messages.
      setHistory((prev) => (prev.length > 0 ? prev : response.messages.map(normalizeMessage)));
      setSessionReady(true);
      return;
    } catch (error) {
      if (sessionIdRef.current !== forSession) return;
      const status = (error as { response?: { status?: number } })?.response?.status;
      if (status !== 404) {
        // Backend unreachable: keep working local-only instead of dying.
        console.error('Failed to load history:', error);
        setSessionReady(true);
        return;
      }
    } finally {
      // The old code set isLoading true and NEVER reset it: the history panel
      // showed "Loading…" forever even with sessions present.
      setIsLoading(false);
    }
    // 404 - this id exists only in this browser; register it with the backend.
    try {
      const created = await apiService.createSession();
      if (sessionIdRef.current !== forSession) return;
      setSessionId(created.session_id);
      storeSessionId(created.session_id);
    } catch (error) {
      console.error('Failed to create session:', error);
    }
    setHistory((prev) => (prev.length > 0 ? prev : []));
    setSessionReady(true);
  }, []);

  // One bootstrap per session id. Without this, the StrictMode remount (and the
  // id change when we create the session) ran bootstrap again and its result
  // overwrote whatever had rendered meanwhile - the welcome bubble vanished.
  const bootstrappedFor = useRef<string | null>(null);

  useEffect(() => {
    if (bootstrappedFor.current === sessionId) return;
    bootstrappedFor.current = sessionId;
    bootstrap();
  }, [bootstrap, sessionId]);

  const createNewSession = useCallback(async () => {
    try {
      const response = await apiService.createSession();
      setSessionId(response.session_id);
      storeSessionId(response.session_id);
      historyRef.current = [];
      setHistory([]);
    } catch (error) {
      // A fabricated id would be rejected by every later call (the backend
      // parses it as a UUID), so mint a fresh one and let the next
      // request surface the outage honestly.
      console.error('Failed to create session:', error);
      const fresh = generateSessionId();
      storeSessionId(fresh);
      setSessionId(fresh);
      historyRef.current = [];
      setHistory([]);
    }
  }, []);

  const addMessage = useCallback((message: Message) => {
    setHistory((prev) => [...prev, message]);
  }, []);

  /**
   * Pull rows the server knows about but this tab has never seen — that is
   * how a caregiver's helper note (POST /api/share/{token}/annotate, written
   * from another browser) reaches the user without a manual reload. Messages
   * this tab itself produced exist twice (local uuid + server row), so a
   * same-role, same-content message within a 3-minute window is treated as
   * already shown, not appended again. Returns what was added so the caller
   * can announce it.
   */
  const pollRemoteMessages = useCallback(async (): Promise<Message[]> => {
    // Serialized: two overlapping polls computed against the same snapshot
    // would append the same rows twice.
    if (pollRemoteBusyRef.current) return [];
    pollRemoteBusyRef.current = true;
    try {
      const forSession = sessionIdRef.current;
      const response = await fetchLatestHistory(forSession);
      if (sessionIdRef.current !== forSession) return [];
      const prev = historyRef.current;
      const known = new Set(prev.map((m) => m.id));
      const added = response.messages
        .map(normalizeMessage)
        .filter((m) => !known.has(m.id))
        // Own messages exist twice (local uuid + server row): suppress only a
        // near-simultaneous echo (3-min window), not every future repeat —
        // saying "yes" twice must appear twice. Screen narrations are the
        // exception that used to slip through: this tab renders them with a
        // "Screen update: " prefix (ChatInterface.handleNarration) while the
        // server row carries the bare text, so the content comparison never
        // matched and every narration was appended a SECOND time ~15s later
        // (double TTS + double live-region announcement + corrupted history).
        // Compare with the prefix stripped.
        .filter((m) => {
          const stripped = m.content.replace(/^Screen update: /, '');
          return !prev.some((p) => {
            const local = p.content.replace(/^Screen update: /, '');
            return p.role === m.role
              && (local === stripped || p.content === m.content)
              && Math.abs(p.timestamp.getTime() - m.timestamp.getTime()) < 180000;
          });
        });
      if (added.length) {
        // Re-check inside the updater: a message may have landed between the
        // fetch above and this setState - append only what is still new.
        setHistory((current) => {
          const currentKnown = new Set(current.map((m) => m.id));
          const fresh = added.filter((m) => !currentKnown.has(m.id));
          return fresh.length ? [...current, ...fresh] : current;
        });
      }
      return added;
    } catch {
      // Backend unreachable: try again on the next tick, silently.
      return [];
    } finally {
      pollRemoteBusyRef.current = false;
    }
  }, []);

  const updateMessage = useCallback((id: string, updates: Partial<Message>) => {
    setHistory((prev) => 
      prev.map((msg) => (msg.id === id ? { ...msg, ...updates } : msg))
    );
  }, []);

  /** Recent sessions for the history panel. Silent on 404/503: demo mode and
   * unreachable backends keep the previous list instead of erroring - an
   * outage must not present as "you have no sessions". */
  const loadSessions = useCallback(async () => {
    try {
      const response = await apiService.listSessions();
      setSessions(response.sessions);
    } catch {
      // keep previous list
    }
  }, []);

  // Bootstrap refreshes the list whenever the session set may have changed.
  useEffect(() => {
    loadSessions();
  }, [loadSessions, sessionId, sessionReady]);

  /** Jump to a previous session; the bootstrap effect loads its history.
   * History MUST be cleared here: bootstrap's "never wipe on-screen messages"
   * guard would otherwise keep the PREVIOUS session's transcript on screen
   * and discard the target session's rows entirely. */
  const switchSession = useCallback((id: string) => {
    if (id === sessionId) return;
    bootstrappedFor.current = null;
    historyRef.current = [];
    setHistory([]);
    setSessionReady(false);
    setSessionId(id);
    storeSessionId(id);
  }, [sessionId]);

  return {
    sessionId,
    history,
    isLoading,
    sessionReady,
    sessions,
    loadSessions,
    switchSession,
    createNewSession,
    addMessage,
    updateMessage,
    pollRemoteMessages,
  };
}