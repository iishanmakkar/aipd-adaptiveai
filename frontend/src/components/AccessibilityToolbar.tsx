import { useCallback } from 'react';
import type { FontSize, ContrastMode, DisabilityProfile, LanguageComplexity } from '../types/accessibility';
import type { Verbosity } from '../types/api';
import { FONT_SIZE_MAP } from '../types/accessibility';

interface AccessibilityToolbarProps {
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
  onReset: () => void;
}

const FONT_SIZES: { value: FontSize; label: string }[] = [
  { value: 'small', label: 'Small' },
  { value: 'medium', label: 'Medium' },
  { value: 'large', label: 'Large' },
  { value: 'xlarge', label: 'X-Large' },
];

const VERBOSITY_LEVELS: { value: Verbosity; label: string }[] = [
  { value: 'concise', label: 'Concise' },
  { value: 'standard', label: 'Standard' },
  { value: 'detailed', label: 'Detailed' },
];

const DISABILITY_PROFILES: { value: DisabilityProfile; label: string }[] = [
  { value: 'none', label: 'None' },
  { value: 'blind', label: 'Blind' },
  { value: 'low_vision', label: 'Low Vision' },
  { value: 'cognitive', label: 'Cognitive' },
  { value: 'motor', label: 'Motor' },
];

const LANGUAGE_COMPLEXITIES: { value: LanguageComplexity; label: string }[] = [
  { value: 'simple', label: 'Simple' },
  { value: 'standard', label: 'Standard' },
  { value: 'technical', label: 'Technical' },
];

export function AccessibilityToolbar({
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
  onReset,
}: AccessibilityToolbarProps) {
  const handleFontSizeChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    const v = e.target.value as FontSize;
    if (FONT_SIZES.some((o) => o.value === v)) onFontSizeChange(v);
  }, [onFontSizeChange]);

  const handleVerbosityChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    const v = e.target.value as Verbosity;
    if (VERBOSITY_LEVELS.some((o) => o.value === v)) onVerbosityChange(v);
  }, [onVerbosityChange]);

  const handleDisabilityProfileChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    const v = e.target.value as DisabilityProfile;
    if (DISABILITY_PROFILES.some((o) => o.value === v)) onDisabilityProfileChange(v);
  }, [onDisabilityProfileChange]);

  const handleLanguageComplexityChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    const v = e.target.value as LanguageComplexity;
    if (LANGUAGE_COMPLEXITIES.some((o) => o.value === v)) onLanguageComplexityChange(v);
  }, [onLanguageComplexityChange]);

  const handleVoiceSpeedChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const v = parseFloat(e.target.value);
    if (!Number.isFinite(v)) return;
    onVoiceSpeedChange(v);
  }, [onVoiceSpeedChange]);

  const handleUiScaleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const v = parseFloat(e.target.value);
    if (!Number.isFinite(v)) return;
    onUiScaleChange(v);
  }, [onUiScaleChange]);

  // NOTE: no manual Enter/Space -> click() here. These are native <button>
  // elements: the browser fires activation itself, and a manual keydown
  // handler double-fired (or swallowed repeat) on some browsers.

  return (
    <div className="accessibility-toolbar" role="toolbar" aria-label="Accessibility settings">
      <fieldset className="toolbar-group">
        <legend>Text Size</legend>
        <select
          value={fontSize}
          onChange={handleFontSizeChange}
          className="toolbar-select"
          aria-label="Select font size"
        >
          {FONT_SIZES.map(({ value, label }) => (
            <option key={value} value={value}>
              {label} ({FONT_SIZE_MAP[value]})
            </option>
          ))}
        </select>
      </fieldset>

      <fieldset className="toolbar-group">
        <legend>Disability Profile</legend>
        <select
          value={disabilityProfile}
          onChange={handleDisabilityProfileChange}
          className="toolbar-select"
          aria-label="Select disability profile for adapted responses"
        >
          {DISABILITY_PROFILES.map(({ value, label }) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </fieldset>

      <fieldset className="toolbar-group">
        <legend>Language Complexity</legend>
        <select
          value={languageComplexity}
          onChange={handleLanguageComplexityChange}
          className="toolbar-select"
          aria-label="Select language complexity level"
        >
          {LANGUAGE_COMPLEXITIES.map(({ value, label }) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </fieldset>

      <fieldset className="toolbar-group">
        <legend>Answer Detail</legend>
        <select
          value={verbosity}
          onChange={handleVerbosityChange}
          className="toolbar-select"
          aria-label="Select answer detail level"
        >
          {VERBOSITY_LEVELS.map(({ value, label }) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </fieldset>

      <fieldset className="toolbar-group">
        <legend>Contrast</legend>
        {/* Constant names on the toggle buttons below: an "Enable/Disable ..."
            name FLIPS with state, so NVDA/JAWS announce "Disable high contrast
            mode, pressed" when contrast is ON — the state reads backwards.
            aria-pressed alone carries the state. */}
        <button
          type="button"
          className={`toolbar-button ${contrastMode === 'high' ? 'active' : ''}`}
          onClick={onContrastToggle}

          aria-pressed={contrastMode === 'high'}
          aria-label="High contrast"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 18a6 6 0 0 0 0-12v12z" />
          </svg>
          <span>High Contrast</span>
        </button>
      </fieldset>

      <fieldset className="toolbar-group">
        <legend>Voice Speed</legend>
        <div className="voice-speed-control">
          <input
            type="range"
            min={0.5}
            max={2}
            step={0.1}
            value={voiceSpeed}
            onChange={handleVoiceSpeedChange}
            className="voice-speed-slider"
            aria-label="Voice speed"
            aria-valuemin={0.5}
            aria-valuemax={2}
            aria-valuenow={Number.isFinite(voiceSpeed) ? voiceSpeed : 1}
          />
          <span className="voice-speed-value" aria-hidden="true">
            {Number.isFinite(voiceSpeed) ? voiceSpeed.toFixed(1) : '1.0'}x
          </span>
        </div>
      </fieldset>

      <fieldset className="toolbar-group">
        <legend>UI Size (low vision)</legend>
        <div className="voice-speed-control">
          <input
            type="range"
            min={1}
            max={2}
            step={0.1}
            value={Number.isFinite(uiScale) ? uiScale : 1}
            onChange={handleUiScaleChange}
            className="voice-speed-slider"
            aria-label="Interface size"
            aria-valuemin={1}
            aria-valuemax={2}
            aria-valuenow={Number.isFinite(uiScale) ? uiScale : 1}
            aria-valuetext={`${Math.round((Number.isFinite(uiScale) ? uiScale : 1) * 100)} percent`}
          />
          <span className="voice-speed-value" aria-hidden="true">
            {Math.round((Number.isFinite(uiScale) ? uiScale : 1) * 100)}%
          </span>
        </div>
      </fieldset>

      <fieldset className="toolbar-group">
        <legend>Readability</legend>
        <button
          type="button"
          className={`toolbar-button ${boldText ? 'active' : ''}`}
          onClick={onBoldToggle}
          aria-pressed={boldText}
          aria-label="Bold text"
        >
          <span>Bold text</span>
        </button>
        <button
          type="button"
          className={`toolbar-button ${wideSpacing ? 'active' : ''}`}
          onClick={onSpacingToggle}
          aria-pressed={wideSpacing}
          aria-label="Wide spacing"
        >
          <span>Wide spacing</span>
        </button>
      </fieldset>

      <fieldset className="toolbar-group">
        <legend>Display</legend>
        <button
          type="button"
          className={`toolbar-button ${darkMode ? 'active' : ''}`}
          onClick={onDarkToggle}
          aria-pressed={darkMode}
          aria-label="Dark mode"
        >
          <span>Dark mode</span>
        </button>
        <button
          type="button"
          className={`toolbar-button ${readingFocus ? 'active' : ''}`}
          onClick={onReadingToggle}
          aria-pressed={readingFocus}
          aria-label="Reading focus"
          title="Dim every answer except the one under your cursor"
        >
          <span>Reading focus</span>
        </button>
      </fieldset>

      <fieldset className="toolbar-group">
        <legend>App Voice</legend>
        <button
          type="button"
          className={`toolbar-button ${muted ? 'active' : ''}`}
          onClick={onMuteToggle}
          aria-pressed={muted}
          aria-label="App voice"
          title="Mute app voice (screen-reader-only mode keeps text announcements)"
        >
          <span>{muted ? 'Unmute voice' : 'Mute voice'}</span>
        </button>
      </fieldset>

      <button
        type="button"
        className="toolbar-button reset-button"
        onClick={onReset}

        aria-label="Reset accessibility settings to defaults"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
          <path d="M21 12v5h-5" />
        </svg>
        <span>Reset</span>
      </button>
    </div>
  );
}