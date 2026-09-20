/**
 * Round 9: real-time screen monitoring of the live browser-agent session's
 * page.
 *
 * Consent model (this is the load-bearing part, not polish):
 * - `active` only becomes true after the user takes an explicit action
 *   (button, Alt+W, or the "watch my screen" voice command through chat) -
 *   never on mount, never by default;
 * - while active, a persistent visual indicator renders (in ChatInterface)
 *   AND a polite live region announces the state, so a screen-reader user
 *   hears that capture is on;
 * - one action stops it: the same button, the same shortcut, or saying
 *   "stop watching my screen". `stop()` also cancels any in-flight TTS;
 * - polling lives only while active: when stopped, this hook issues no
 *   further /api/monitor/events requests, so no narrations are pulled and
 *   nothing new can be spoken.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { apiService } from '../services/api';
import { useTextToSpeech } from './useTextToSpeech';
import type { NarrationEvent } from '../types/api';

const POLL_MS = 3000;

export function useScreenMonitor(sessionId: string | null,
                                 onNarration?: (n: NarrationEvent) => void) {
  const [active, setActive] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sinceRef = useRef(0);
  const activeRef = useRef(false);
  const timerRef = useRef<number | null>(null);
  const { speak, stop: stopSpeech } = useTextToSpeech();
  const onNarrationRef = useRef(onNarration);
  onNarrationRef.current = onNarration;

  const pollOnce = useCallback(async () => {
    if (!activeRef.current || !sessionId) return;
    try {
      const data = await apiService.monitorEvents(sessionId, sinceRef.current);
      sinceRef.current = data.cursor ?? sinceRef.current;
      if (!data.active) {
        // Backend/browser says monitoring ended (idle sweep, session close,
        // max-duration cap). Reflect that honestly instead of polling on.
        activeRef.current = false;
        setActive(false);
        return;
      }
      for (const event of data.narrations ?? []) {
        onNarrationRef.current?.(event);
        // Narrations interrupt nothing: the user is not speaking - this is
        // the assistant's turn. User input always outranks it because sending
        // a message stops speech (see ChatInterface).
        stopSpeech();
        speak(event.text);
      }
    } catch {
      // A failed poll must not kill monitoring; the next tick retries.
    }
  }, [sessionId, speak, stopSpeech]);

  useEffect(() => {
    if (!active || !sessionId) return;
    const tick = () => {
      void pollOnce();
    };
    tick();
    timerRef.current = window.setInterval(tick, POLL_MS);
    return () => {
      if (timerRef.current !== null) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [active, sessionId, pollOnce]);

  const start = useCallback(async (): Promise<string> => {
    if (!sessionId) return 'No chat session - start a conversation first.';
    setStarting(true);
    setError(null);
    try {
      const res = await apiService.monitorStart(sessionId);
      sinceRef.current = 0;
      activeRef.current = true;
      setActive(true);
      const message = res.message ?? 'Watching the live page.';
      speak(message);
      return message;
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      const message = detail || 'Could not start monitoring.';
      setError(message);
      return message;
    } finally {
      setStarting(false);
    }
  }, [sessionId, speak]);

  const stop = useCallback(async (): Promise<string> => {
    stopSpeech(); // the kill switch outranks a narration mid-sentence
    activeRef.current = false;
    setActive(false);
    if (!sessionId) return 'Stopped.';
    try {
      await apiService.monitorStop(sessionId);
      return 'Stopped watching. Nothing further is captured or sent.';
    } catch {
      return 'Stopped watching locally; the service was unreachable.';
    }
  }, [sessionId, stopSpeech]);

  const toggle = useCallback(async (): Promise<string> => {
    return activeRef.current ? stop() : start();
  }, [start, stop]);

  // Re-adopt state on mount / session change: if monitoring is already
  // running server-side (e.g., the page reloaded, or monitoring was started
  // by the voice command), the indicator and narration polling must come
  // back - the indicator must never silently lie.
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    apiService.monitorEvents(sessionId, 0)
      .then((data) => {
        if (cancelled) return;
        sinceRef.current = data.cursor ?? sinceRef.current;
        if (data.active) {
          activeRef.current = true;
          setActive(true);
        }
      })
      .catch(() => { /* service unreachable: stay off */ });
    return () => { cancelled = true; };
  }, [sessionId]);

  // One-action stop via keyboard: Alt+W toggles monitoring. Registered only
  // while a session exists; ignored while typing (Alt+W has no text effect,
  // but avoid surprising combos inside inputs).
  useEffect(() => {
    if (!sessionId) return;
    const handler = (e: KeyboardEvent) => {
      if (e.altKey && (e.key === 'w' || e.key === 'W')) {
        e.preventDefault();
        void toggle();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [sessionId, toggle]);

  // Unmount (e.g., navigating away from the chat): stop speaking.
  useEffect(() => () => stopSpeech(), [stopSpeech]);

  return { active, starting, error, start, stop, toggle };
}
