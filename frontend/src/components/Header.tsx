import { useCallback } from 'react';
import type { FontSize, ContrastMode } from '../types/accessibility';
import { AccessibilityToolbar } from './AccessibilityToolbar';

interface HeaderProps {
  sessionId: string;
  onNewSession: () => void;
  fontSize: FontSize;
  contrastMode: ContrastMode;
  voiceSpeed: number;
  onFontSizeChange: (size: FontSize) => void;
  onContrastToggle: () => void;
  onVoiceSpeedChange: (speed: number) => void;
  onResetAccessibility: () => void;
  showAccessibility: boolean;
  onToggleAccessibility: () => void;
}

export function Header({
  sessionId,
  onNewSession,
  fontSize,
  contrastMode,
  voiceSpeed,
  onFontSizeChange,
  onContrastToggle,
  onVoiceSpeedChange,
  onResetAccessibility,
  showAccessibility,
  onToggleAccessibility,
}: HeaderProps) {
  const shortSessionId = useCallback(() => {
    return sessionId.slice(-8);
  }, [sessionId]);

  return (
    <header className="app-header" role="banner">
      <div className="header-left">
        <h1 className="app-title">AdaptiveAI</h1>
        <span className="app-subtitle" aria-label="Session ID">
          {shortSessionId()}
        </span>
      </div>

      <div className="header-center">
        <button
          type="button"
          className="header-button"
          onClick={onToggleAccessibility}
          aria-expanded={showAccessibility}
          aria-controls="accessibility-toolbar"
          aria-label={showAccessibility ? 'Hide accessibility settings' : 'Show accessibility settings'}
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
          <span className="visually-hidden">{showAccessibility ? 'Hide' : 'Show'} accessibility settings</span>
        </button>
      </div>

      <div className="header-right">
        <button
          type="button"
          className="header-button new-session-button"
          onClick={onNewSession}
          aria-label="Start new session"
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
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
            onFontSizeChange={onFontSizeChange}
            onContrastToggle={onContrastToggle}
            onVoiceSpeedChange={onVoiceSpeedChange}
            onReset={onResetAccessibility}
          />
        </div>
      )}
    </header>
  );
}