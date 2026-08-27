import { v4 as uuidv4 } from 'uuid';

const SESSION_STORAGE_KEY = 'adaptiveai-session-id';

export function generateSessionId(): string {
  return uuidv4();
}

export function getStoredSessionId(): string | null {
  try {
    return localStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function storeSessionId(sessionId: string): void {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  } catch {
    // Ignore storage errors (e.g., private browsing)
  }
}

export function clearSessionId(): void {
  try {
    localStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    // Ignore
  }
}

export function getOrCreateSessionId(): string {
  let sessionId = getStoredSessionId();
  if (!sessionId) {
    sessionId = generateSessionId();
    storeSessionId(sessionId);
  }
  return sessionId;
}