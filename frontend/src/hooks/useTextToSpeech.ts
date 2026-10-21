import { useState, useCallback, useRef, useEffect } from 'react';
import { enqueueSpeech, cancelSpeech, onSpeechQueueChange, speechQueueDepth } from '../utils/speechQueue';

interface UseTextToSpeechReturn {
  // 'silent' means the text was NOT spoken aloud: no speechSynthesis in this
  // browser, or an explicit mute at volume 0. Callers must not describe content
  // as heard or fully listened to after a 'silent' result.
  speak: (text: string) => Promise<'spoken' | 'silent'>;
  stop: () => void;
  isSpeaking: boolean;
  supported: boolean;
}

export function useTextToSpeech(): UseTextToSpeechReturn {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const voicesLoadedRef = useRef(false);

  const supported = 'speechSynthesis' in window;

  useEffect(() => {
    if (!supported) return;
    setIsSpeaking(speechQueueDepth() > 0);
    return onSpeechQueueChange(() => setIsSpeaking(speechQueueDepth() > 0));
  }, [supported]);

  useEffect(() => {
    if (!supported) return;

    const loadVoices = () => {
      voicesLoadedRef.current = true;
    };

    // addEventListener (not onvoiceschanged assignment): every hook instance
    // (chat + monitor) assigning the global handler stomped the others, and
    // unmounting one nulled a live other's handler.
    speechSynthesis.addEventListener('voiceschanged', loadVoices);

    // Force load voices
    speechSynthesis.getVoices();
    loadVoices();

    return () => {
      speechSynthesis.removeEventListener('voiceschanged', loadVoices);
    };
  }, [supported]);

  const getPreferredVoice = useCallback((): SpeechSynthesisVoice | null => {
    if (!supported) return null;

    const voices = speechSynthesis.getVoices();
    if (voices.length === 0) return null;

    // Prefer natural, English voices
    const preferred = voices.find((v) =>
      v.lang.startsWith('en') && (v.name.includes('Natural') || v.name.includes('Premium') || v.name.includes('Google'))
    );

    return preferred || voices.find((v) => v.lang.startsWith('en')) || voices[0] || null;
  }, [supported]);

  // Voice selection feeds the shared queue, which owns utterance construction.
  const speak = useCallback(async (text: string): Promise<'spoken' | 'silent'> => {
    if (!supported) return 'silent';

    // Apply user preferences from CSS custom properties
    const rawRate = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--voice-rate') || '1');
    const rawPitch = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--voice-pitch') || '1');
    const rawVolume = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--voice-volume') || '1');
    const rate = Number.isFinite(rawRate) ? rawRate : 1;
    const pitch = Number.isFinite(rawPitch) ? rawPitch : 1;
    const volume = Number.isFinite(rawVolume) ? rawVolume : 1;
    // Muted (volume 0, e.g. screen-reader-only users who drive NVDA's own voice
    // and want no app audio): resolve as 'silent' without queueing, so callers
    // never hang - and never count a sound nobody heard.
    if (volume === 0) return 'silent';

    await enqueueSpeech(text, { rate, pitch, volume, voice: getPreferredVoice() });
    return 'spoken';
  }, [supported, getPreferredVoice]);

  // Dev-only handle so frontend/tts_proof.py can drive this real hook in a real
  // Chromium. import.meta.env.DEV is statically false in a production build, so
  // the assignment is dead-code-eliminated and ships no test backdoor.
  if (import.meta.env.DEV) {
    (window as unknown as Record<string, unknown>).__adaptiveai_test_speak = speak;
  }

  const stop = useCallback(() => {
    cancelSpeech();
    setIsSpeaking(false);
  }, []);

  return {
    speak,
    stop,
    isSpeaking,
    supported,
  };
}