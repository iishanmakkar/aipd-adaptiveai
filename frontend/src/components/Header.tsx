import { useCallback, useEffect, useRef, useState } from 'react';
import { useDialogFocus } from '../hooks/useDialogFocus';
import type { FontSize, ContrastMode, DisabilityProfile, LanguageComplexity } from '../types/accessibility';
import type { Verbosity } from '../types/api';
import { AccessibilityToolbar } from './AccessibilityToolbar';

interface HeaderProps {
  sessionId: string;
  email: string | null;
  onNewSession: () => void;
  onToggleHistory: () => void;
  onDownloadTranscript: () => void;
  canDownload: boolean;
  onShare: () => void;
  shareBusy: boolean;
  accountMessage: string;
  onSignOut: () => void;
  onDeleteAccount: () => void;
  confirmDeleteAccount: boolean;
  onRequestDeleteAccount: () => void;
  onCancelDeleteAccount: () => void;
  fontSize: FontSize;
  contrastMode: ContrastMode;
  voiceSpeed: number;
  muted: boolean;
  uiScale: number;
  boldText: boolean;
  wideSpacing: boolean;
  darkMode: boolean;
  readingFocus: boolean;
  verbosity: Verbosity;
  disabilityProfile: DisabilityProfile;
  languageComplexity: LanguageComplexity;
  onFontSizeChange: (size: FontSize) => void;
  onContrastToggle: () => void;
  onVoiceSpeedChange: (speed: number) => void;
  onMuteToggle: () => void;
  onUiScaleChange: (scale: number) => void;
  onBoldToggle: () => void;
  onSpacingToggle: () => void;
  onDarkToggle: () => void;
  onReadingToggle: () => void;
  onVerbosityChange: (level: Verbosity) => void;
  onDisabilityProfileChange: (profile: DisabilityProfile) => void;
  onLanguageComplexityChange: (complexity: LanguageComplexity) => void;
  onResetAccessibility: () => void;
  showAccessibility: boolean;
  onToggleAccessibility: () => void;
}

export function Header({
  sessionId,
  email,
  onNewSession,
  onToggleHistory,
  onDownloadTranscript,
  canDownload,
  onShare,
  shareBusy,
  accountMessage,
  onSignOut,
  onDeleteAccount,
  confirmDeleteAccount,
  onRequestDeleteAccount,
  onCancelDeleteAccount,
  fontSize,
  contrastMode,
  voiceSpeed,
  muted,
  uiScale,
  boldText,
  wideSpacing,
  darkMode,
  readingFocus,
  verbosity,
  disabilityProfile,
  languageComplexity,
  onFontSizeChange,
  onContrastToggle,
  onVoiceSpeedChange,
  onMuteToggle,
  onUiScaleChange,
  onBoldToggle,
  onSpacingToggle,
  onDarkToggle,
  onReadingToggle,
  onVerbosityChange,
  onDisabilityProfileChange,
  onLanguageComplexityChange,
  onResetAccessibility,
  showAccessibility,
  onToggleAccessibility,
}: HeaderProps) {
  const shortSessionId = useCallback(() => {
    return sessionId.slice(-8);
  }, [sessionId]);
  const [showAccount, setShowAccount] = useState(false);
  const accountRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  useDialogFocus(showAccount, accountRef);
  useDialogFocus(showAccessibility, panelRef, false);
  // Closing the popover must also drop the delete confirmation: otherwise
  // reopening lands straight on "Yes, delete everything" and one misclick
  // deletes. All three close paths funnel through here.
  const closeAccount = useCallback(() => {
    setShowAccount(false);
    onCancelDeleteAccount();
  }, [onCancelDeleteAccount]);
  // The accessibility panel's own Escape handling lives in ChatInterface; this
  // one only covers the account popover.
  useEffect(() => {
    if (!showAccount) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeAccount();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [showAccount, closeAccount]);

  return (
    <header className="app-header" role="banner">
      <div className="header-brand">
        <div className="brand-mark" aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="16" cy="4" r="1" />
            <path d="m18 19 1-7-6 1" />
            <path d="m5 8 3-3 5.5 3-2.36 3.5" />
            <path d="M4.24 14.5a5 5 0 0 0 6.88 6" />
            <path d="M13.76 17.5a5 5 0 0 0-6.88-6" />
          </svg>
        </div>
        <div className="brand-text">
          <h1 className="app-title">AdaptiveAI</h1>
          <span className="app-tagline">Accessibility Assistant</span>
        </div>
        <span className="session-chip" aria-label="Session ID">
          {shortSessionId()}
        </span>
      </div>

      <div className="header-actions">
        <button
          type="button"
          className="header-button"
          onClick={onToggleHistory}
          aria-label="Open session history"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M21 12v5h-5" />
          </svg>
          <span className="visually-hidden">History</span>
        </button>

        <button
          type="button"
          className="header-button"
          onClick={onDownloadTranscript}
          disabled={!canDownload}
          aria-label="Download conversation transcript"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          <span className="visually-hidden">Download transcript</span>
        </button>

        <button
          type="button"
          className="header-button"
          onClick={onToggleAccessibility}
          aria-expanded={showAccessibility}
          aria-controls="accessibility-toolbar"
          aria-label={showAccessibility ? 'Hide accessibility settings' : 'Show accessibility settings'}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
          <span className="visually-hidden">{showAccessibility ? 'Hide' : 'Show'} accessibility settings</span>
        </button>

        <button
          type="button"
          className="header-button"
          onClick={onNewSession}
          aria-label="Start new session"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
          <span className="visually-hidden">New session</span>
        </button>

        <button
          type="button"
          className="header-button"
          onClick={onShare}
          disabled={shareBusy || !canDownload}
          aria-label="Share this session with a helper so they can watch and leave spoken notes"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <circle cx="18" cy="5" r="3" />
            <circle cx="6" cy="12" r="3" />
            <circle cx="18" cy="19" r="3" />
            <line x1="8.6" y1="13.5" x2="15.4" y2="17.5" />
            <line x1="15.4" y1="6.5" x2="8.6" y2="10.5" />
          </svg>
          <span className="visually-hidden">Share with a helper</span>
        </button>

        <button
          type="button"
          className="header-button header-account"
          onClick={() => setShowAccount((open) => !open)}
          aria-expanded={showAccount}
          aria-controls="account-menu"
          aria-label={email ? `Account: ${email}` : 'Account'}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
            <circle cx="12" cy="7" r="4" />
          </svg>
          <span className="visually-hidden">Account menu</span>
        </button>
      </div>

      {showAccount && (
        <div
          id="account-menu"
          ref={accountRef}
          className="account-menu"
          role="dialog"
          aria-modal="true"
          aria-label="Account"
        >
          <p className="account-email">{email ? `Signed in as ${email}` : 'Signed in'}</p>
          {accountMessage && (
            <p className="account-share-message" role="status">{accountMessage}</p>
          )}
          <button type="button" className="account-action" onClick={onShare} disabled={shareBusy}>
            {shareBusy ? 'Creating share link…' : 'Create a share link for a helper'}
          </button>
          <button type="button" className="account-action" onClick={onSignOut}>Sign out</button>
          {confirmDeleteAccount ? (
            <div className="account-confirm">
              <p>Delete this account and every message, session and preference in
                it? This cannot be undone.</p>
              <div className="account-confirm-row">
                <button type="button" className="account-danger" onClick={onDeleteAccount}>
                  Yes, delete everything
                </button>
                <button type="button" onClick={onCancelDeleteAccount}>Keep my account</button>
              </div>
            </div>
          ) : (
            <button type="button" className="account-action account-danger" onClick={onRequestDeleteAccount}>
              Delete my account and data
            </button>
          )}
          <button type="button" onClick={closeAccount}>Close (Esc)</button>
        </div>
      )}

      {showAccessibility && (
        <div
          id="accessibility-toolbar"
          ref={panelRef}
          className="accessibility-panel"
          role="region"
          aria-label="Accessibility settings"
        >
          <AccessibilityToolbar
            fontSize={fontSize}
            contrastMode={contrastMode}
            voiceSpeed={voiceSpeed}
            muted={muted}
            uiScale={uiScale}
            boldText={boldText}
            wideSpacing={wideSpacing}
            darkMode={darkMode}
            readingFocus={readingFocus}
            verbosity={verbosity}
            disabilityProfile={disabilityProfile}
            languageComplexity={languageComplexity}
            onFontSizeChange={onFontSizeChange}
            onContrastToggle={onContrastToggle}
            onVoiceSpeedChange={onVoiceSpeedChange}
            onMuteToggle={onMuteToggle}
            onUiScaleChange={onUiScaleChange}
            onBoldToggle={onBoldToggle}
            onSpacingToggle={onSpacingToggle}
            onDarkToggle={onDarkToggle}
            onReadingToggle={onReadingToggle}
            onVerbosityChange={onVerbosityChange}
            onDisabilityProfileChange={onDisabilityProfileChange}
            onLanguageComplexityChange={onLanguageComplexityChange}
            onReset={onResetAccessibility}
          />
        </div>
      )}
    </header>
  );
}