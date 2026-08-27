import { useCallback } from 'react';
import type { FontSize, ContrastMode } from '../types/accessibility';
import { FONT_SIZE_MAP } from '../types/accessibility';

interface AccessibilityToolbarProps {
  fontSize: FontSize;
  contrastMode: ContrastMode;
  voiceSpeed: number;
  onFontSizeChange: (size: FontSize) => void;
  onContrastToggle: () => void;
  onVoiceSpeedChange: (speed: number) => void;
  onReset: () => void;
}

const FONT_SIZES: { value: FontSize; label: string }[] = [
  { value: 'small', label: 'Small' },
  { value: 'medium', label: 'Medium' },
  { value: 'large', label: 'Large' },
  { value: 'xlarge', label: 'X-Large' },
];

export function AccessibilityToolbar({
  fontSize,
  contrastMode,
  voiceSpeed,
  onFontSizeChange,
  onContrastToggle,
  onVoiceSpeedChange,
  onReset,
}: AccessibilityToolbarProps) {
  const handleFontSizeChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    onFontSizeChange(e.target.value as FontSize);
  }, [onFontSizeChange]);

  const handleVoiceSpeedChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    onVoiceSpeedChange(parseFloat(e.target.value));
  }, [onVoiceSpeedChange]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      e.currentTarget.click();
    }
  }, []);

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
        <legend>Contrast</legend>
        <button
          type="button"
          className={`toolbar-button ${contrastMode === 'high' ? 'active' : ''}`}
          onClick={onContrastToggle}
          onKeyDown={handleKeyDown}
          aria-pressed={contrastMode === 'high'}
          aria-label={contrastMode === 'high' ? 'Disable high contrast mode' : 'Enable high contrast mode'}
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
            aria-valuenow={voiceSpeed}
          />
          <span className="voice-speed-value" aria-hidden="true">{voiceSpeed.toFixed(1)}x</span>
        </div>
      </fieldset>

      <button
        type="button"
        className="toolbar-button reset-button"
        onClick={onReset}
        onKeyDown={handleKeyDown}
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