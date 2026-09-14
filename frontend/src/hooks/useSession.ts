import { useState, useCallback, useEffect, useRef } from 'react';
import { getOrCreateSessionId, storeSessionId, clearSessionId } from '../utils/session';
import { apiService } from '../services/api';
import type { Message } from '../types/chat';
import type { HistoryMessage, SessionSummary } from '../types/api';

/**
 * Map a history API row onto the UI Message shape: `created_at` is an ISO
 * string on the wire, but MessageBubble calls Date methods on `timestamp`, and
 * feeding it the raw string crashed the whole chat on reload.
 */
function normalizeMessage(m: HistoryMessage): Message {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    timestamp: new Date(m.created_at),
    agent_used: m.agent_used ?? undefined,
  };
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
  const bootstrap = useCallback(async () => {
    setIsLoading(true);
    setSessionReady(false);
    try {
      const response = await apiService.getHistory(sessionId);
      // Never wipe what is already on screen: a restore that races user
      // activity (or StrictMode's second pass) must not delete messages.
      setHistory((prev) => (prev.length > 0 ? prev : response.messages.map(normalizeMessage)));
      setSessionReady(true);
      return;
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status;
      if (status !== 404) {
        // Backend unreachable: keep working local-only instead of dying.
        console.error('Failed to load history:', error);
        setSessionReady(true);
        return;
      }
    }
    // 404 - this id exists only in this browser; register it with the backend.
    try {
      const created = await apiService.createSession();
      setSessionId(created.session_id);
      storeSessionId(created.session_id);
    } catch (error) {
      console.error('Failed to create session:', error);
    }
    setHistory((prev) => (prev.length > 0 ? prev : []));
    setSessionReady(true);
  }, [sessionId]);

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
      setHistory([]);
    } catch (error) {
      console.error('Failed to create session:', error);
      // Fallback to local session
      const newSessionId = `session-${Date.now()}`;
      setSessionId(newSessionId);
      storeSessionId(newSessionId);
      setHistory([]);
    }
  }, []);

  const addMessage = useCallback((message: Message) => {
    setHistory((prev) => [...prev, message]);
  }, []);

  const updateMessage = useCallback((id: string, updates: Partial<Message>) => {
    setHistory((prev) => 
      prev.map((msg) => (msg.id === id ? { ...msg, ...updates } : msg))
    );
  }, []);

  const clearSession = useCallback(() => {
    clearSessionId();
    const newSessionId = `session-${Date.now()}`;
    setSessionId(newSessionId);
    storeSessionId(newSessionId);
    setHistory([]);
  }, []);

  /** Recent sessions for the history panel. Silent on 404/503: demo mode and
   * unreachable backends just show an empty list instead of erroring. */
  const loadSessions = useCallback(async () => {
    try {
      const response = await apiService.listSessions();
      setSessions(response.sessions);
    } catch {
      setSessions([]);
    }
  }, []);

  // Bootstrap refreshes the list whenever the session set may have changed.
  useEffect(() => {
    loadSessions();
  }, [loadSessions, sessionId, sessionReady]);

  /** Jump to a previous session; the bootstrap effect loads its history. */
  const switchSession = useCallback((id: string) => {
    if (id === sessionId) return;
    bootstrappedFor.current = null;
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
    clearSession,
  };
}