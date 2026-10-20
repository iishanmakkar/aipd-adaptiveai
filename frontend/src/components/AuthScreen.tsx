/** Sign in / create account. The whole app sits behind this: without a bearer
 * token the backend's authenticated routes answer 401, so this is not an
 * optional screen - it is how a user gets an identity, preferences and history
 * that stay theirs.
 */
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { apiService } from '../services/api';
import { describeApiError } from '../utils/apiError';
import { signIn, takeSessionExpired } from '../utils/auth';
import { enqueueSpeech } from '../utils/speechQueue';

type Mode = 'login' | 'register';

export function AuthScreen() {
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const emailRef = useRef<HTMLInputElement>(null);
  // Read once: why is this user on the login screen? A blindfolded user gets
  // no visual cue that their session ended — the app has to SAY it.
  const [arrivedFromExpiry] = useState(() => takeSessionExpired());

  // A keyboard/screen-reader user should land inside the form, not on the
  // page background, the moment this screen appears — and, blindfolded, they
  // must HEAR what this screen is and what to do with it.
  useEffect(() => {
    emailRef.current?.focus();
    void enqueueSpeech(
      arrivedFromExpiry
        ? 'Your session has ended. Please sign in again. Type your email address, press Tab, type your password, then press Enter.'
        : 'AdaptiveAI. Sign in screen. Type your email address, press Tab, type your password, then press Enter to continue.',
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once per screen mount
  }, []);

  // Errors are role=alert for screen readers, but a blindfolded user without
  // one has only this app's voice — speak every sign-in failure.
  useEffect(() => {
    if (error) void enqueueSpeech(error);
  }, [error]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const m = mode;
    setBusy(true);
    setError('');
    try {
      const token = m === 'login'
        ? await apiService.login(email.trim(), password)
        : await apiService.register(email.trim(), password);
      if (!token?.access_token) throw new Error('Sign-in returned no token.');
      signIn(token.access_token, email.trim());
    } catch (err) {
      setError(readableError(err, m));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-screen">
      <a className="skip-link" href="#main-content">Skip to sign in</a>
      <main id="main-content" tabIndex={-1} className="auth-main">
      <form className="auth-card" onSubmit={submit} aria-labelledby="auth-title">
        <h1 id="auth-title">AdaptiveAI</h1>
        <p className="auth-subtitle">
          Context-aware help for forms, documents, tickets and pages - by voice,
          text, or screen reader.
        </p>

        <div className="auth-mode" role="group" aria-label="Choose account action">
          <button
            type="button"
            className={mode === 'login' ? 'auth-mode-active' : ''}
            aria-pressed={mode === 'login'}
            onClick={() => { setMode('login'); setError(''); }}
          >
            Sign in
          </button>
          <button
            type="button"
            className={mode === 'register' ? 'auth-mode-active' : ''}
            aria-pressed={mode === 'register'}
            onClick={() => { setMode('register'); setError(''); }}
          >
            Create account
          </button>
        </div>

        <label htmlFor="auth-email">Email address</label>
        <input
          ref={emailRef}
          id="auth-email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />

        <label htmlFor="auth-password">Password</label>
        <input
          id="auth-password"
          type="password"
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          required
          minLength={mode === 'register' ? 8 : undefined}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {mode === 'register' && (
          <p className="auth-hint">At least 8 characters. Stored hashed; nothing is sent to a third party.</p>
        )}

        <button type="submit" className="auth-submit" disabled={busy}>
          {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account and continue'}
        </button>

        {/* role=alert: an error here must interrupt, not wait to be discovered.
            Rendered only when there IS an error: an always-mounted empty
            alert (or a dual role+aria-live) announces stale blanks. */}
        {error && <p id="auth-error" className="auth-error" role="alert">{error}</p>}
      </form>
      </main>
    </div>
  );
}

function readableError(err: unknown, mode: Mode): string {
  const status = (err as { response?: { status?: number } }).response?.status;
  if (status === 401) return 'That email and password combination is not recognised.';
  if (status === 400 && mode === 'register') {
    return 'That account already exists - sign in instead.';
  }
  const described = describeApiError(err);
  if (status === 422) {
    return mode === 'register' && described.toLowerCase().includes('email')
      ? 'That email address does not look right. Use a full address like name@example.com.'
      : described;
  }
  return described;
}
