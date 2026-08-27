import { useEffect, useRef, useState, useCallback } from 'react';
import { formatDuration } from '../utils/audio';

interface MicButtonProps {
  onStartRecording: () => Promise<void>;
  onStopRecording: () => Promise<void> | void;
  onCancelRecording: () => void;
  isRecording: boolean;
  recordingTime: number;
  disabled?: boolean;
  error?: string | null;
}

export function MicButton({
  onStartRecording,
  onStopRecording,
  onCancelRecording,
  isRecording,
  recordingTime,
  disabled = false,
  error,
}: MicButtonProps) {
  const [isPressed, setIsPressed] = useState(false);
  const pressTimerRef = useRef<number | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const handleMouseDown = useCallback(async () => {
    if (disabled) return;
    setIsPressed(true);
    pressTimerRef.current = window.setTimeout(async () => {
      await onStartRecording();
    }, 150);
  }, [disabled, onStartRecording]);

  const handleMouseUp = useCallback(() => {
    if (pressTimerRef.current) {
      clearTimeout(pressTimerRef.current);
      pressTimerRef.current = null;
    }
    setIsPressed(false);
    if (isRecording) {
      onStopRecording();
    }
  }, [isRecording, onStopRecording]);

  const handleMouseLeave = useCallback(() => {
    if (pressTimerRef.current) {
      clearTimeout(pressTimerRef.current);
      pressTimerRef.current = null;
    }
    setIsPressed(false);
    if (isRecording) {
      onCancelRecording();
    }
  }, [isRecording, onCancelRecording]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault();
      handleMouseDown();
    }
  }, [handleMouseDown]);

  const handleKeyUp = useCallback((e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault();
      handleMouseUp();
    }
  }, [handleMouseUp]);

  // Handle long press for touch devices
  const handleTouchStart = useCallback((e: React.TouchEvent<HTMLButtonElement>) => {
    e.preventDefault();
    handleMouseDown();
  }, [handleMouseDown]);

  const handleTouchEnd = useCallback((e: React.TouchEvent<HTMLButtonElement>) => {
    e.preventDefault();
    handleMouseUp();
  }, [handleMouseUp]);

  useEffect(() => {
    return () => {
      if (pressTimerRef.current) {
        clearTimeout(pressTimerRef.current);
      }
    };
  }, []);

  return (
    <div className="mic-button-container">
      <button
        ref={buttonRef}
        type="button"
        className={`mic-button ${isRecording ? 'recording' : ''} ${isPressed ? 'pressed' : ''} ${error ? 'error' : ''}`}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onKeyDown={handleKeyDown}
        onKeyUp={handleKeyUp}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
        disabled={disabled}
        aria-label={isRecording ? 'Stop recording (release to send)' : 'Hold to record voice message'}
        aria-pressed={isRecording}
        aria-disabled={disabled}
        aria-describedby={error ? 'mic-error' : undefined}
      >
        <span className="mic-icon" aria-hidden="true">
          {isRecording ? (
            <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <rect x="6" y="4" width="4" height="16" rx="2" />
              <rect x="14" y="4" width="4" height="16" rx="2" />
            </svg>
          ) : (
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="22" />
              <line x1="8" y1="22" x2="16" y2="22" />
            </svg>
          )}
        </span>
        {isRecording && (
          <span className="recording-indicator" aria-hidden="true">
            <span className="pulse-ring"></span>
            <span className="pulse-ring"></span>
            <span className="pulse-ring"></span>
          </span>
        )}
      </button>
      
      {isRecording && (
        <div className="recording-info" role="status" aria-live="polite" aria-label={`Recording for ${formatDuration(recordingTime)}`}>
          <span className="recording-time">{formatDuration(recordingTime)}</span>
          <span className="recording-hint">Release to send</span>
        </div>
      )}
      
      {error && (
        <div id="mic-error" className="mic-error" role="alert" aria-live="assertive">
          {error}
        </div>
      )}
    </div>
  );
}