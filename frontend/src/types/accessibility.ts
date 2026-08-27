export type FontSize = 'small' | 'medium' | 'large' | 'xlarge';
export type ContrastMode = 'normal' | 'high';

export interface AccessibilityPreferences {
  fontSize: FontSize;
  contrastMode: ContrastMode;
  voiceSpeed: number;
  voicePitch: number;
  voiceVolume: number;
  reduceMotion: boolean;
}

export const DEFAULT_ACCESSIBILITY_PREFS: AccessibilityPreferences = {
  fontSize: 'medium',
  contrastMode: 'normal',
  voiceSpeed: 1.0,
  voicePitch: 1.0,
  voiceVolume: 1.0,
  reduceMotion: false,
};

export const FONT_SIZE_MAP: Record<FontSize, string> = {
  small: '0.875rem',
  medium: '1rem',
  large: '1.25rem',
  xlarge: '1.5rem',
};

export const STORAGE_KEY = 'adaptiveai-accessibility-prefs';