import { useEffect, useState } from 'react';
import { AuthScreen } from './components/AuthScreen';
import { ChatInterface } from './components/ChatInterface';
import { SharedSession } from './components/SharedSession';
import { getToken, onSessionChange } from './utils/auth';
import { apiService } from './services/api';
import './styles/main.css';

/** A share link is either /shared/<token> (what the backend hands out) or the
 * hash form, so opening it from a chat app that mangles paths still works.
 * A trailing period (sentence punctuation glued to the URL by a client that
 * extracted it from prose) must not break the route. */
function sharedToken(): string | null {
  const fromHash = window.location.hash.match(/^#\/shared\/([A-Za-z0-9_-]+)/);
  if (fromHash) return fromHash[1] ?? null;
  const fromPath = window.location.pathname.match(/^\/shared\/([A-Za-z0-9_-]+)[.)]?\/?$/);
  return fromPath ? fromPath[1] ?? null : null;
}

function App() {
  const [authed, setAuthed] = useState<boolean>(() => !!getToken());
  const [shareToken] = useState<string | null>(() => sharedToken());

  useEffect(() => onSessionChange(() => setAuthed(!!getToken())), []);

  // A stored token may be expired or revoked (secret rotation, deleted
  // account). Validate it once on boot: a 401 trips the api interceptor's
  // expireSession, which flips the app to the login screen immediately instead
  // of letting the user compose into a dead session.
  useEffect(() => {
    if (getToken()) void apiService.me().catch(() => { /* interceptor handles expiry */ });
  }, []);

  if (shareToken) {
    return <SharedSession token={shareToken} />;
  }

  if (!authed) {
    return <AuthScreen />;
  }

  return (
    <div className="app">
      {/* First stop for a keyboard or screen-reader user: jump past the header
          and the toolbar straight into the conversation. */}
      <a className="skip-link" href="#main-content">Skip to the conversation</a>
      <ChatInterface />
    </div>
  );
}

export default App;
