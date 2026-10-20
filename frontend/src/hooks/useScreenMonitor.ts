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
import { describeApiError } from '../utils/apiError';
import { useTextToSpeech } from './useTextToSpeech';
import type { NarrationEvent } from '../types/api';

const POLL_MS = 3000;

export function useScreenMonitor(sessionId: string | null,
                                 onNarration?: (n: NarrationEvent) => void) {
  const [active, setActive] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeRef = useRef(false);
  const pollingRef = useRef(false);
  const cancelledRef = useRef(false);
  const failuresRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const { speak, stop: stopSpeech } = useTextToSpeech();
  const onNarrationRef = useRef(onNarration);
  onNarrationRef.current = onNarration;

  const pollOnce = useCallback(async () => {
    // No overlapping polls: a slow TTS chain must not interleave with the
    // next tick's batch (shared FIFO already orders within a batch).
    if (!activeRef.current || !sessionId || pollingRef.current) return;
    pollingRef.current = true;
    try {
      const data = await apiService.monitorEvents(sessionId);
      failuresRef.current = 0;
      if (!data.active) {
        // Backend/browser says monitoring ended (idle sweep, session close,
        // max-duration cap). Reflect that honestly instead of polling on.
        activeRef.current = false;
        setActive(false);
        return;
      }
      // Shared FIFO speaks head-to-tail: no per-event cancel, no clipping.
      // User input still outranks the queue - sending a message stops speech.
      for (const event of data.narrations ?? []) {
        if (cancelledRef.current || !activeRef.current) break;
        onNarrationRef.current?.(event);
        // Narrations interrupt nothing: the user is not speaking - this is
        // the assistant's turn. User input always outranks it because sending
        // a message stops speech (see ChatInterface).
        await speak(event.text);
      }
    } catch (e: unknown) {
      // A failed poll must not kill monitoring; the next tick retries. But
      // failures must not be silent forever either: after several in a row
      // the "watching" indicator is a lie (backend dead, session swept), so
      // say so and stop polling. Auth/gone-session failures stop at once.
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status === 401 || status === 404) {
        activeRef.current = false;
        setActive(false);
        setError('Monitoring stopped: the session is gone or not signed in.');
        return;
      }
      failuresRef.current += 1;
      if (failuresRef.current > 3) {
        activeRef.current = false;
        setActive(false);
        setError('Lost contact with the monitoring service - stopped watching.');
      }
    } finally {
      pollingRef.current = false;
    }
  }, [sessionId, speak]);

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
    // Defensive: a wedged poll flag from an older run must not silently
    // disable the fresh one (the poll loop early-returns while it is set).
    pollingRef.current = false;
    failuresRef.current = 0;
    try {
      const res = await apiService.monitorStart(sessionId);
      pollingRef.current = false;
      failuresRef.current = 0;
      activeRef.current = true;
      setActive(true);
      const message = res.message ?? 'Watching the live page.';
      void speak(message);
      return message;
    } catch (e: unknown) {
      // describeApiError, because FastAPI sends validation failures as an array
      // of objects and this text is spoken and rendered verbatim.
      const message = describeApiError(e, 'Could not start monitoring.');
      setError(message);
      void speak(message);
      return message;
    } finally {
      setStarting(false);
    }
  }, [sessionId, speak]);

  const stop = useCallback(async (): Promise<string> => {
    stopSpeech(); // the kill switch outranks a narration mid-sentence
    activeRef.current = false;
    setActive(false);
    // A stuck poll flag would silently eat the next start's ticks.
    pollingRef.current = false;
    failuresRef.current = 0;
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
    apiService.monitorEvents(sessionId)
      .then((data) => {
        if (cancelled) return;
        if (data.active) {
          pollingRef.current = false;
          failuresRef.current = 0;
          activeRef.current = true;
          setActive(true);
        }
      })
      .catch(() => { /* service unreachable: stay off */ });
    return () => { cancelled = true; };
  }, [sessionId]);

  // One-action stop via keyboard: Alt+W toggles monitoring. Registered only
  // while a session exists. Skipped inside editable fields despite what the
  // old comment claimed: toggling mid-typing stole the keystroke.
  useEffect(() => {
    if (!sessionId) return;
    const handler = (e: KeyboardEvent) => {
      if (e.altKey && (e.key === 'w' || e.key === 'W')) {
        const target = e.target as HTMLElement | null;
        if (target?.closest?.('input,textarea,select,[contenteditable]')) return;
        e.preventDefault();
        void toggle();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [sessionId, toggle]);

  // Unmount (e.g., navigating away from the chat): stop speaking and
  // retire the in-flight poll loop so no narration lands after unmount.
  useEffect(() => {
    cancelledRef.current = false;
    return () => {
      cancelledRef.current = true;
      stopSpeech();
    };
  }, [stopSpeech]);

  return { active, starting, error, start, stop, toggle };
}
