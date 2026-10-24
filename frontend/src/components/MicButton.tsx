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
    // Touch devices fire pointerdown AND touchstart for one gesture; without
    // this guard both scheduled a start → two getUserMedia races, the loser's
    // stream leaked with the mic indicator stuck on.
    if (pressTimerRef.current) return;
    setIsPressed(true);
    pressTimerRef.current = window.setTimeout(async () => {
      pressTimerRef.current = null;
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

  /**
   * Drifting off the button while holding it must not throw the recording away.
   * That was the old behaviour, and it punished exactly the users this product
   * is for: a tremor, a sliding thumb, or a magnifier that moves the cursor off
   * the target lost everything they had just dictated. Recording therefore
   * continues until a deliberate stop (release, second key press) or an
   * explicit cancel (Escape).
   */
  const handlePointerLeave = useCallback(() => {
    if (isRecording) return;
    if (pressTimerRef.current) {
      // Released before the hold threshold: nothing was recorded, so nothing
      // is lost by clearing the pending start.
      clearTimeout(pressTimerRef.current);
      pressTimerRef.current = null;
    }
    setIsPressed(false);
  }, [isRecording]);

  const handlePointerDown = useCallback((event: React.PointerEvent<HTMLButtonElement>) => {
    // Pointer capture delivers the release to this button even when the
    // pointer has wandered off it - the mechanism behind the rule above.
    event.currentTarget.setPointerCapture?.(event.pointerId);
    void handleMouseDown();
  }, [handleMouseDown]);

  useEffect(() => {
    if (!isRecording) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        // Discarding the dictation must not ALSO close the host dialog on
        // the same keypress (it used to throw away every value the user had
        // already typed). stopImmediatePropagation keeps the later-registered
        // window listeners - the dialog's close-on-Escape - out of this press.
        event.stopImmediatePropagation();
        onCancelRecording();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isRecording, onCancelRecording]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== ' ' && e.key !== 'Enter') return;
    if (e.repeat) return; // holding Space must not re-fire start races
    e.preventDefault();
    // A keyboard or screen-reader user presses and releases in well under the
    // 150ms hold threshold, so treating the key as a "hold" meant recording
    // could never start. From the keyboard the key is a toggle instead: first
    // press records, second press stops and sends. (preventDefault above also
    // suppresses the synthetic click, so onClick below never double-toggles.)
    if (isRecording) {
      onStopRecording();
    } else if (!isPressed) {
      setIsPressed(true);
      onStartRecording();
    }
  }, [isRecording, isPressed, onStartRecording, onStopRecording]);

  const handleClick = useCallback((e: React.MouseEvent<HTMLButtonElement>) => {
    // Assistive-tech "Activate" fires a synthetic click (detail 0) with no
    // key or pointer events first - without this, NVDA/virtual-cursor users
    // could not operate the mic at all. Real mouse clicks (detail >= 1)
    // already went through the pointer handlers; keyboard clicks are
    // suppressed by the preventDefault above. Only detail-0 reaches here.
    if (e.detail !== 0) return;
    if (isRecording) {
      onStopRecording();
    } else {
      void onStartRecording();
    }
  }, [isRecording, onStartRecording, onStopRecording]);

  const handleKeyUp = useCallback((e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault();
      // Visual pressed state only - recording keeps going until the next press.
      setIsPressed(false);
    }
  }, []);

  // Handle long press for touch devices
  // NOTE: no onTouchStart/onTouchEnd — pointer events already cover touch,
  // and the extra handlers double-fired stop (two transcriptions). Kept only
  // onPointerDown/onPointerUp (+ onKeyDown/onClick for keyboard/AT).

  useEffect(() => {
    return () => {
      if (pressTimerRef.current) {
        clearTimeout(pressTimerRef.current);
      }
    };
  }, []);

  return (
    <div className="mic-button-container">
      <span id="mic-usage-hint" className="visually-hidden">
        Hold the mouse button to record and release to send. Moving off the
        button while holding it keeps recording. With a keyboard, press Enter or
        Space to start recording and press it again to stop and send; press
        Escape to discard the recording.
      </span>
      <button
        ref={buttonRef}
        type="button"
        className={`mic-button ${isRecording ? 'recording' : ''} ${isPressed ? 'pressed' : ''} ${error ? 'error' : ''}`}
        onPointerDown={handlePointerDown}
        onPointerUp={handleMouseUp}
        onPointerLeave={handlePointerLeave}
        onKeyDown={handleKeyDown}
        onKeyUp={handleKeyUp}
        onClick={handleClick}
        disabled={disabled}
        aria-label={isRecording ? 'Stop recording and send' : 'Record voice message'}
        aria-pressed={isRecording}
        aria-disabled={disabled}
        aria-describedby={error ? 'mic-usage-hint mic-error' : 'mic-usage-hint'}
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
        <div className="recording-info" role="status" aria-live="polite">
          {/* Announce start/stop once: the ticking time below is aria-hidden
            so screen readers are not re-announced every second. */}
          <span className="visually-hidden">Recording in progress</span>
          <span className="recording-time" aria-hidden="true">{formatDuration(recordingTime)}</span>
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