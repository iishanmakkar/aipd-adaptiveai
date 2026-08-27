import { useState, useEffect, useCallback } from 'react';
import type { AccessibilityPreferences, FontSize, ContrastMode } from '../types/accessibility';
import { DEFAULT_ACCESSIBILITY_PREFS, FONT_SIZE_MAP, STORAGE_KEY } from '../types/accessibility';

export function useAccessibility() {
  const [prefs, setPrefs] = useState<AccessibilityPreferences>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        return { ...DEFAULT_ACCESSIBILITY_PREFS, ...JSON.parse(stored) };
      }
    } catch {
      // Ignore parse errors
    }
    return DEFAULT_ACCESSIBILITY_PREFS;
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch {
      // Ignore
    }
    
    // Apply CSS custom properties
    document.documentElement.style.setProperty('--font-size-base', FONT_SIZE_MAP[prefs.fontSize]);
    document.documentElement.style.setProperty('--voice-rate', prefs.voiceSpeed.toString());
    document.documentElement.style.setProperty('--voice-pitch', prefs.voicePitch.toString());
    document.documentElement.style.setProperty('--voice-volume', prefs.voiceVolume.toString());
    
    // Apply contrast mode
    if (prefs.contrastMode === 'high') {
      document.documentElement.classList.add('high-contrast');
    } else {
      document.documentElement.classList.remove('high-contrast');
    }
    
    // Apply reduce motion
    if (prefs.reduceMotion) {
      document.documentElement.classList.add('reduce-motion');
    } else {
      document.documentElement.classList.remove('reduce-motion');
    }
  }, [prefs]);

  const setFontSize = useCallback((size: FontSize) => {
    setPrefs((prev) => ({ ...prev, fontSize: size }));
  }, []);

  const setContrastMode = useCallback((mode: ContrastMode) => {
    setPrefs((prev) => ({ ...prev, contrastMode: mode }));
  }, []);

  const toggleContrast = useCallback(() => {
    setPrefs((prev) => ({
      ...prev,
      contrastMode: prev.contrastMode === 'high' ? 'normal' : 'high',
    }));
  }, []);

  const setVoiceSpeed = useCallback((speed: number) => {
    setPrefs((prev) => ({ ...prev, voiceSpeed: Math.max(0.5, Math.min(2, speed)) }));
  }, []);

  const setVoicePitch = useCallback((pitch: number) => {
    setPrefs((prev) => ({ ...prev, voicePitch: Math.max(0.5, Math.min(2, pitch)) }));
  }, []);

  const setVoiceVolume = useCallback((volume: number) => {
    setPrefs((prev) => ({ ...prev, voiceVolume: Math.max(0, Math.min(1, volume)) }));
  }, []);

  const setReduceMotion = useCallback((reduce: boolean) => {
    setPrefs((prev) => ({ ...prev, reduceMotion: reduce }));
  }, []);

  const resetToDefaults = useCallback(() => {
    setPrefs(DEFAULT_ACCESSIBILITY_PREFS);
  }, []);

  return {
    prefs,
    setFontSize,
    setContrastMode,
    toggleContrast,
    setVoiceSpeed,
    setVoicePitch,
    setVoiceVolume,
    setReduceMotion,
    resetToDefaults,
  };
}