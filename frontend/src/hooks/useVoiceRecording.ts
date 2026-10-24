import { useState, useRef, useCallback, useEffect } from 'react';
import { createAudioBlob } from '../utils/audio';

// Hard cap for one recording, in seconds.
const MAX_RECORDING_SECONDS = 30;

interface UseVoiceRecordingOptions {
  /** Called with the captured audio when the 30s cap auto-stops a recording.
   * Manual stops deliver through MicButton; without this the cap path
   * silently dropped the audio (found live: a 30s hold lost everything). */
  onAutoStop?: (blob: Blob) => void;
}

interface UseVoiceRecordingReturn {
  isRecording: boolean;
  recordingTime: number;
  audioBlob: Blob | null;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<Blob | null>;
  cancelRecording: () => void;
  error: string | null;
}

export function useVoiceRecording(options: UseVoiceRecordingOptions = {}): UseVoiceRecordingReturn {
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Latest-callback ref: the cap effect must always deliver to the CURRENT
  // handler without re-registering on every render.
  const onAutoStopRef = useRef(options.onAutoStop);
  onAutoStopRef.current = options.onAutoStop;

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<number | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunkCountRef = useRef(0);
  // Cleanup runs after state is gone, so "was I recording?" must live in a ref.
  const isRecordingRef = useRef(false);
  // Set by the unmount cleanup; the pending getUserMedia continuation checks
  // it, because the permission prompt can outlive the component.
  const unmountedRef = useRef(false);

  useEffect(() => {
    isRecordingRef.current = isRecording;
  }, [isRecording]);

  const startRecording = useCallback(async () => {
    // Re-entrancy guard, checked SYNCHRONOUSLY (the state effect lags a
    // render): the keyboard toggle plus a fast second press used to start TWO
    // recordings and leak the first stream with the mic indicator stuck on.
    if (isRecordingRef.current) return;
    isRecordingRef.current = true;
    setError(null);
    setAudioBlob(null);
    chunksRef.current = [];
    chunkCountRef.current = 0;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }
      });

      // The permission prompt can outlive this component: an unmount while
      // getUserMedia is pending used to orphan the continuation - it started
      // a recorder nobody could stop and left the OS microphone HOT with no
      // way for the user to know (they cannot see the indicator). If the
      // component is gone, release the device immediately.
      if (unmountedRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      
      const mt = typeof MediaRecorder !== 'undefined' && (MediaRecorder as unknown as { isTypeSupported?: (t: string) => boolean }).isTypeSupported?.('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus' : '';
      const mediaRecorder = mt ? new MediaRecorder(stream, { mimeType: mt }) : new MediaRecorder(stream);
      
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
          // Draft-as-you-go: an async IndexedDB write cannot be relied on to
          // finish during a page unload, so the parking spot is refreshed
          // every ~2s while recording (20 chunks at the 100ms timeslice).
          // The unmount/pagehide persist below is then only the last-mile.
          chunkCountRef.current += 1;
          if (chunkCountRef.current % 20 === 0) {
            const draft = createAudioBlob(chunksRef.current, mediaRecorder.mimeType);
            if (draft.size > 0) {
              void import('../utils/offlineQueue')
                .then(({ saveAudioDraft }) => saveAudioDraft(draft))
                .catch(() => { /* IndexedDB unavailable - recovery just won't exist */ });
            }
          }
        }
      };

      mediaRecorder.onstop = () => {
        const blob = createAudioBlob(chunksRef.current, mediaRecorder.mimeType);
        setAudioBlob(blob);
        stream.getTracks().forEach((track) => track.stop());
      };

      mediaRecorder.start(100);
      setIsRecording(true);
      setRecordingTime(0);

      timerRef.current = window.setInterval(() => {
        setRecordingTime((prev) => prev + 1);
      }, 1000);
    } catch (err) {
      isRecordingRef.current = false;
      setError(err instanceof Error ? err.message : 'Failed to start recording');
      setIsRecording(false);
    }
  }, []);

  /**
   * Stop recording and resolve with the captured audio.
   *
   * This must return a Promise resolved from MediaRecorder's `onstop`: the blob
   * only exists once that async event fires, so the old signature (returning
   * the `audioBlob` state synchronously) handed back `null` for the first
   * recording - and the *previous* recording's blob for any later one - which
   * made transcription silently impossible.
   */
  const stopRecording = useCallback((): Promise<Blob | null> => {
    return new Promise((resolve) => {
      const recorder = mediaRecorderRef.current;
      // Ref (synchronous), not state (lags a render): a double stop (touch
      // pointerup + mouseup, two rapid keys) used to call recorder.stop()
      // twice - the second threw InvalidStateError inside the executor and
      // rejected unhandled, and could double-transcribe.
      if (!recorder || !isRecordingRef.current) {
        resolve(null);
        return;
      }
      isRecordingRef.current = false;
      recorder.onstop = () => {
        const blob = createAudioBlob(chunksRef.current, recorder.mimeType);
        setAudioBlob(blob);
        streamRef.current?.getTracks().forEach((track) => track.stop());
        resolve(blob);
      };
      try {
        recorder.stop();
      } catch {
        resolve(null);
      }
      setIsRecording(false);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    });
  }, []);

  // Auto-stop at the cap. This must react to state rather than read
  // `recordingTime` inside the interval callback: that closure captured 0, so
  // the 30-second limit never fired and recordings ran until manual stop.
  // The captured audio is delivered to onAutoStop — the old code stopped the
  // recorder and threw the blob away, losing a full 30s of dictation.
  useEffect(() => {
    if (isRecording && recordingTime >= MAX_RECORDING_SECONDS) {
      void (async () => {
        const blob = await stopRecording();
        if (blob && onAutoStopRef.current) onAutoStopRef.current(blob);
      })();
    }
  }, [isRecording, recordingTime, stopRecording]);

  const cancelRecording = useCallback(() => {
    if (mediaRecorderRef.current && isRecordingRef.current) {
      try {
        mediaRecorderRef.current.onstop = null;
        mediaRecorderRef.current.stop();
      } catch {
        /* already stopped */
      }
      try {
        mediaRecorderRef.current.stream.getTracks().forEach((track) => track.stop());
      } catch {
        /* stream gone */
      }
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
    }
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    isRecordingRef.current = false;
    setIsRecording(false);
    setRecordingTime(0);
    setAudioBlob(null);
    chunksRef.current = [];
    // A deliberate cancel discards EVERYTHING - including any draft the
    // chunk-cadence save already parked, or the next load would "recover"
    // a recording the user explicitly threw away.
    void import('../utils/offlineQueue')
      .then(({ clearAudioDraft }) => clearAudioDraft())
      .catch(() => { /* nothing parked, nothing to clear */ });
  }, [isRecording]);

  /**
   * Interrupted-recording recovery: an unmount (sign-out, share-view switch,
   * component teardown) or a page unload while recording used to drop the
   * audio silently. Instead the captured audio is stopped and parked in
   * IndexedDB; the next mount offers to transcribe and send it. A deliberate
   * cancel (Escape) still discards — that path clears the chunks itself.
   */
  const persistDraft = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || !isRecordingRef.current) return;
    try {
      recorder.onstop = null;
      recorder.stop();
    } catch {
      /* already stopped */
    }
    const blob = createAudioBlob(chunksRef.current, recorder.mimeType);
    chunksRef.current = [];
    streamRef.current?.getTracks().forEach((track) => track.stop());
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    isRecordingRef.current = false;
    if (blob.size > 0) {
      void import('../utils/offlineQueue')
        .then(({ saveAudioDraft }) => saveAudioDraft(blob))
        .catch(() => { /* IndexedDB unavailable - the draft is lost, as before */ });
    }
  }, []);

  useEffect(() => {
    const onPageHide = () => {
      if (isRecordingRef.current) persistDraft();
    };
    window.addEventListener('pagehide', onPageHide);
    return () => {
      window.removeEventListener('pagehide', onPageHide);
      if (isRecordingRef.current) persistDraft();
      // A pending getUserMedia (permission prompt still up) must release the
      // device when its continuation resumes, instead of starting an
      // unstoppable recorder on an unmounted component.
      unmountedRef.current = true;
    };
  }, [persistDraft]);

  return {
    isRecording,
    recordingTime,
    audioBlob,
    startRecording,
    stopRecording,
    cancelRecording,
    error,
  };
}