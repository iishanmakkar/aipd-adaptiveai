import { useState, useCallback, useRef, useEffect } from 'react';

interface UseTextToSpeechReturn {
  speak: (text: string) => Promise<void>;
  stop: () => void;
  isSpeaking: boolean;
  supported: boolean;
}

export function useTextToSpeech(): UseTextToSpeechReturn {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const voicesLoadedRef = useRef(false);

  const supported = 'speechSynthesis' in window;

  useEffect(() => {
    if (!supported) return;

    const loadVoices = () => {
      voicesLoadedRef.current = true;
    };

    if (speechSynthesis.onvoiceschanged !== undefined) {
      speechSynthesis.onvoiceschanged = loadVoices;
    }

    // Force load voices
    speechSynthesis.getVoices();
    loadVoices();

    return () => {
      if (speechSynthesis.onvoiceschanged === loadVoices) {
        speechSynthesis.onvoiceschanged = null;
      }
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

  const speak = useCallback(async (text: string): Promise<void> => {
    if (!supported) return;
    
    // Stop any current speech
    speechSynthesis.cancel();

    return new Promise((resolve) => {
      const utterance = new SpeechSynthesisUtterance(text);
      utteranceRef.current = utterance;

      const voice = getPreferredVoice();
      if (voice) {
        utterance.voice = voice;
      }

      // Apply user preferences from CSS custom properties
      const rate = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--voice-rate') || '1');
      const pitch = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--voice-pitch') || '1');
      const volume = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--voice-volume') || '1');

      utterance.rate = rate;
      utterance.pitch = pitch;
      utterance.volume = volume;

      utterance.onstart = () => {
        setIsSpeaking(true);
      };

      utterance.onend = () => {
        setIsSpeaking(false);
        utteranceRef.current = null;
        resolve();
      };

      utterance.onerror = (event) => {
        if (event.error !== 'interrupted') {
          console.error('TTS error:', event.error);
        }
        setIsSpeaking(false);
        utteranceRef.current = null;
        resolve();
      };

      speechSynthesis.speak(utterance);
    });
  }, [supported, getPreferredVoice]);

  const stop = useCallback(() => {
    if (supported) {
      speechSynthesis.cancel();
      setIsSpeaking(false);
      utteranceRef.current = null;
    }
  }, [supported]);

  return {
    speak,
    stop,
    isSpeaking,
    supported,
  };
}