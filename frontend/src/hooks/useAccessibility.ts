import { useState, useEffect, useCallback } from 'react';
import type { AccessibilityPreferences, FontSize, ContrastMode, ThemeMode, DisabilityProfile, LanguageComplexity } from '../types/accessibility';
import { DEFAULT_ACCESSIBILITY_PREFS, FONT_SIZE_MAP, STORAGE_KEY } from '../types/accessibility';

const FONT_SIZES = ['small', 'medium', 'large', 'xlarge'] as const;
const PROFILES = ['none', 'blind', 'low_vision', 'cognitive', 'motor'] as const;
const COMPLEXITIES = ['simple', 'standard', 'technical'] as const;

function sanitizePrefs(raw: unknown): AccessibilityPreferences {
  const base = { ...DEFAULT_ACCESSIBILITY_PREFS };
  if (typeof raw !== 'object' || raw === null) return base;
  const r = raw as Record<string, unknown>;
  if (FONT_SIZES.includes(r.fontSize as FontSize)) base.fontSize = r.fontSize as FontSize;
  if (r.contrastMode === 'high' || r.contrastMode === 'normal') base.contrastMode = r.contrastMode;
  for (const [key, min, max] of [['voiceSpeed', 0.5, 2], ['voicePitch', 0.5, 2], ['voiceVolume', 0, 1]] as const) {
    const v = typeof r[key] === 'number' ? r[key] as number : NaN;
    if (Number.isFinite(v)) base[key] = Math.max(min, Math.min(max, v));
  }
  if (PROFILES.includes(r.disabilityProfile as DisabilityProfile)) base.disabilityProfile = r.disabilityProfile as DisabilityProfile;
  if (COMPLEXITIES.includes(r.languageComplexity as LanguageComplexity)) base.languageComplexity = r.languageComplexity as LanguageComplexity;
  if (typeof r.reduceMotion === 'boolean') base.reduceMotion = r.reduceMotion;
  if (r.theme === 'dark' || r.theme === 'light') base.theme = r.theme;
  const scale = typeof r.uiScale === 'number' ? r.uiScale : NaN;
  if (Number.isFinite(scale)) base.uiScale = Math.max(1, Math.min(2, scale));
  if (typeof r.boldText === 'boolean') base.boldText = r.boldText;
  if (typeof r.wideSpacing === 'boolean') base.wideSpacing = r.wideSpacing;
  if (typeof r.readingFocus === 'boolean') base.readingFocus = r.readingFocus;
  return base;
}

export function useAccessibility() {
  const [prefs, setPrefs] = useState<AccessibilityPreferences>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        return sanitizePrefs(JSON.parse(stored));
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
    
    // Apply CSS custom properties. UI scale multiplies the font-size base so
    // the WHOLE interface (buttons, inputs, dialogs) grows for low vision,
    // not just paragraph text.
    const baseRem = parseFloat(FONT_SIZE_MAP[prefs.fontSize]) || 1;
    document.documentElement.style.setProperty('--font-size-base', `${baseRem * prefs.uiScale}rem`);
    document.documentElement.style.setProperty('--voice-rate', prefs.voiceSpeed.toString());
    document.documentElement.style.setProperty('--voice-pitch', prefs.voicePitch.toString());
    document.documentElement.style.setProperty('--voice-volume', prefs.voiceVolume.toString());
    
    // Apply contrast + theme modes
    if (prefs.contrastMode === 'high') {
      document.documentElement.classList.add('high-contrast');
    } else {
      document.documentElement.classList.remove('high-contrast');
    }
    document.documentElement.classList.toggle('dark-mode', prefs.theme === 'dark');
    
    // Apply reduce motion
    if (prefs.reduceMotion) {
      document.documentElement.classList.add('reduce-motion');
    } else {
      document.documentElement.classList.remove('reduce-motion');
    }

    // Low-vision text amplification
    document.documentElement.classList.toggle('bold-text', prefs.boldText);
    document.documentElement.classList.toggle('wide-spacing', prefs.wideSpacing);
    document.documentElement.classList.toggle('reading-focus', prefs.readingFocus);
  }, [prefs]);

  const setFontSize = useCallback((size: FontSize) => {
    setPrefs((prev) => ({ ...prev, fontSize: size }));
  }, []);

  const setContrastMode = useCallback((mode: ContrastMode) => {
    if (mode !== 'high' && mode !== 'normal') return;
    setPrefs((prev) => ({ ...prev, contrastMode: mode }));
  }, []);

  const setTheme = useCallback((theme: ThemeMode) => {
    if (theme !== 'dark' && theme !== 'light') return;
    setPrefs((prev) => ({ ...prev, theme }));
  }, []);

  const toggleDarkMode = useCallback(() => {
    setPrefs((prev) => ({ ...prev, theme: prev.theme === 'dark' ? 'light' : 'dark' }));
  }, []);

  const toggleContrast = useCallback(() => {
    setPrefs((prev) => ({
      ...prev,
      contrastMode: prev.contrastMode === 'high' ? 'normal' : 'high',
    }));
  }, []);

  const setVoiceSpeed = useCallback((speed: number) => {
    if (!Number.isFinite(speed)) return;
    setPrefs((prev) => ({ ...prev, voiceSpeed: Math.max(0.5, Math.min(2, speed)) }));
  }, []);

  const setVoicePitch = useCallback((pitch: number) => {
    if (!Number.isFinite(pitch)) return;
    setPrefs((prev) => ({ ...prev, voicePitch: Math.max(0.5, Math.min(2, pitch)) }));
  }, []);

  const setVoiceVolume = useCallback((volume: number) => {
    if (!Number.isFinite(volume)) return;
    setPrefs((prev) => ({ ...prev, voiceVolume: Math.max(0, Math.min(1, volume)) }));
  }, []);

  const setReduceMotion = useCallback((reduce: boolean) => {
    setPrefs((prev) => ({ ...prev, reduceMotion: reduce }));
  }, []);

  const setUiScale = useCallback((scale: number) => {
    if (!Number.isFinite(scale)) return;
    setPrefs((prev) => ({ ...prev, uiScale: Math.max(1, Math.min(2, scale)) }));
  }, []);

  const toggleBoldText = useCallback(() => {
    setPrefs((prev) => ({ ...prev, boldText: !prev.boldText }));
  }, []);

  const toggleWideSpacing = useCallback(() => {
    setPrefs((prev) => ({ ...prev, wideSpacing: !prev.wideSpacing }));
  }, []);

  const toggleReadingFocus = useCallback(() => {
    setPrefs((prev) => ({ ...prev, readingFocus: !prev.readingFocus }));
  }, []);

  const setDisabilityProfile = useCallback((profile: DisabilityProfile) => {
    setPrefs((prev) => ({ ...prev, disabilityProfile: profile }));
  }, []);

  const setLanguageComplexity = useCallback((complexity: LanguageComplexity) => {
    setPrefs((prev) => ({ ...prev, languageComplexity: complexity }));
  }, []);

  const resetToDefaults = useCallback(() => {
    setPrefs(DEFAULT_ACCESSIBILITY_PREFS);
  }, []);

  return {
    prefs,
    setFontSize,
    setContrastMode,
    setTheme,
    toggleDarkMode,
    toggleContrast,
    setVoiceSpeed,
    setVoicePitch,
    setVoiceVolume,
    setReduceMotion,
    setUiScale,
    toggleBoldText,
    toggleWideSpacing,
    toggleReadingFocus,
    setDisabilityProfile,
    setLanguageComplexity,
    resetToDefaults,
  };
}