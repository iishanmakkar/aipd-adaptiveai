export type FontSize = 'small' | 'medium' | 'large' | 'xlarge';
export type ContrastMode = 'normal' | 'high';
export type DisabilityProfile = 'none' | 'blind' | 'low_vision' | 'cognitive' | 'motor';
export type LanguageComplexity = 'simple' | 'standard' | 'technical';

export interface AccessibilityPreferences {
  fontSize: FontSize;
  contrastMode: ContrastMode;
  voiceSpeed: number;
  voicePitch: number;
  voiceVolume: number;
  reduceMotion: boolean;
  disabilityProfile: DisabilityProfile;
  languageComplexity: LanguageComplexity;
}

export const DEFAULT_ACCESSIBILITY_PREFS: AccessibilityPreferences = {
  fontSize: 'medium',
  contrastMode: 'normal',
  voiceSpeed: 1.0,
  voicePitch: 1.0,
  voiceVolume: 1.0,
  reduceMotion: false,
  disabilityProfile: 'none',
  languageComplexity: 'standard',
};

export const FONT_SIZE_MAP: Record<FontSize, string> = {
  small: '0.875rem',
  medium: '1rem',
  large: '1.25rem',
  xlarge: '1.5rem',
};

export const DISABILITY_PROFILE_LABELS: Record<DisabilityProfile, string> = {
  none: 'None',
  blind: 'Blind',
  low_vision: 'Low Vision',
  cognitive: 'Cognitive',
  motor: 'Motor',
};

export const LANGUAGE_COMPLEXITY_LABELS: Record<LanguageComplexity, string> = {
  simple: 'Simple',
  standard: 'Standard',
  technical: 'Technical',
};

export const STORAGE_KEY = 'adaptiveai-accessibility-prefs';