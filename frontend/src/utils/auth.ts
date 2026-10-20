/** Where the bearer JWT lives, and how a 401 gets back to the login screen.
 *
 * `adaptiveai_token` is the key the offline queue drain in main.tsx already
 * reads, so a queued preference save made while signed out replays with the
 * right identity once the user signs in.
 */
const TOKEN_KEY = 'adaptiveai_token';
const EMAIL_KEY = 'adaptiveai_email';
const EXPIRED_KEY = 'adaptiveai_session_expired';

type Listener = () => void;
const listeners = new Set<Listener>();

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getEmail(): string | null {
  try {
    return localStorage.getItem(EMAIL_KEY);
  } catch {
    return null;
  }
}

export function signIn(token: string, email: string): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(EMAIL_KEY, email);
  emit();
}

export function signOut(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(EMAIL_KEY);
  emit();
}

/** Called by the API layer when the server rejects the stored token, so the
 * app can show the login screen instead of a wall of failed requests. The
 * expired flag lets the auth screen SAY why the user is there — blindfolded,
 * a silent bounce to login looks like the app broke. */
export function expireSession(): void {
  try {
    sessionStorage.setItem(EXPIRED_KEY, '1');
  } catch {
    /* sessionStorage unavailable - the notice is just not shown */
  }
  signOut();
}

/** True exactly once when the login screen opened because a live session
 * ended (expiry, rotation, deleted account) rather than a plain visit. */
export function takeSessionExpired(): boolean {
  try {
    const expired = sessionStorage.getItem(EXPIRED_KEY) === '1';
    if (expired) sessionStorage.removeItem(EXPIRED_KEY);
    return expired;
  } catch {
    return false;
  }
}

function emit(): void {
  listeners.forEach((listener) => listener());
}

export function onSessionChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
