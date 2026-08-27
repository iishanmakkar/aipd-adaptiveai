import { useState, useCallback, useEffect } from 'react';
import { getOrCreateSessionId, storeSessionId, clearSessionId } from '../utils/session';
import { apiService } from '../services/api';
import { mockApi } from '../services/mockApi';
import type { Message } from '../types/chat';

const USE_MOCK_API = import.meta.env.VITE_USE_MOCK === 'true';

export function useSession() {
  const [sessionId, setSessionId] = useState<string>(() => getOrCreateSessionId());
  const [history, setHistory] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    loadHistory();
  }, [sessionId]);

  const loadHistory = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = USE_MOCK_API 
        ? await mockApi.getHistory(sessionId)
        : await apiService.getHistory(sessionId);
      setHistory(response.messages);
    } catch (error) {
      console.error('Failed to load history:', error);
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  const createNewSession = useCallback(async () => {
    try {
      const response = USE_MOCK_API 
        ? await mockApi.createSession()
        : await apiService.createSession();
      const newSessionId = response.session_id;
      setSessionId(newSessionId);
      storeSessionId(newSessionId);
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

  return {
    sessionId,
    history,
    isLoading,
    createNewSession,
    addMessage,
    updateMessage,
    clearSession,
  };
}