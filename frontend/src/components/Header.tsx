import { useCallback } from 'react';
import type { FontSize, ContrastMode } from '../types/accessibility';
import type { Verbosity } from '../types/api';
import { AccessibilityToolbar } from './AccessibilityToolbar';

interface HeaderProps {
  sessionId: string;
  onNewSession: () => void;
  onToggleHistory: () => void;
  onDownloadTranscript: () => void;
  canDownload: boolean;
  fontSize: FontSize;
  contrastMode: ContrastMode;
  voiceSpeed: number;
  verbosity: Verbosity;
  onFontSizeChange: (size: FontSize) => void;
  onContrastToggle: () => void;
  onVoiceSpeedChange: (speed: number) => void;
  onVerbosityChange: (level: Verbosity) => void;
  onResetAccessibility: () => void;
  showAccessibility: boolean;
  onToggleAccessibility: () => void;
}

export function Header({
  sessionId,
  onNewSession,
  onToggleHistory,
  onDownloadTranscript,
  canDownload,
  fontSize,
  contrastMode,
  voiceSpeed,
  verbosity,
  onFontSizeChange,
  onContrastToggle,
  onVoiceSpeedChange,
  onVerbosityChange,
  onResetAccessibility,
  showAccessibility,
  onToggleAccessibility,
}: HeaderProps) {
  const shortSessionId = useCallback(() => {
    return sessionId.slice(-8);
  }, [sessionId]);

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
      </div>

      {showAccessibility && (
        <div
          id="accessibility-toolbar"
          className="accessibility-panel"
          role="region"
          aria-label="Accessibility settings"
        >
          <AccessibilityToolbar
            fontSize={fontSize}
            contrastMode={contrastMode}
            voiceSpeed={voiceSpeed}
            verbosity={verbosity}
            onFontSizeChange={onFontSizeChange}
            onContrastToggle={onContrastToggle}
            onVoiceSpeedChange={onVoiceSpeedChange}
            onVerbosityChange={onVerbosityChange}
            onReset={onResetAccessibility}
          />
        </div>
      )}
    </header>
  );
}