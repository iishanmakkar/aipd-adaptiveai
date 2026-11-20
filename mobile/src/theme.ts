export type Theme = {
  bg: string;
  surface: string;
  surfaceAlt: string;
  border: string;
  text: string;
  textDim: string;
  accent: string;
  accentText: string;
  /** Soft accent wash for selected states, chips, and the listening orb ring. */
  accentSoft: string;
  danger: string;
  /** Text/icon color that reads on top of danger — dark themes need a near-black label, light themes white. */
  onDanger: string;
  dangerSoft: string;
  ok: string;
  okSoft: string;
  warn: string;
  warnSoft: string;
  /** Shadow base color — screens use it with a shared elevation recipe. */
  shadow: string;
  /** Scrim behind modal dialogs. */
  backdrop: string;
  radius: number;
};

const dark: Theme = {
  bg: '#0B0F14',
  surface: '#141A22',
  surfaceAlt: '#1C242E',
  border: '#28323D',
  text: '#F2F6FA',
  textDim: '#9AA7B4',
  accent: '#76B900',
  accentText: '#08110A',
  accentSoft: 'rgba(118,185,0,0.16)',
  danger: '#FF6B6B',
  onDanger: '#1A0606',
  dangerSoft: 'rgba(255,107,107,0.15)',
  ok: '#4ADE80',
  okSoft: 'rgba(74,222,128,0.14)',
  warn: '#FBBF24',
  warnSoft: 'rgba(251,191,36,0.14)',
  shadow: '#000000',
  backdrop: 'rgba(0,0,0,0.72)',
  radius: 16,
};

const darkHighContrast: Theme = {
  ...dark,
  bg: '#000000',
  surface: '#0A0A0A',
  surfaceAlt: '#161616',
  border: '#FFFFFF',
  text: '#FFFFFF',
  textDim: '#E8E8E8',
  accent: '#FFD400',
  accentText: '#000000',
  accentSoft: 'rgba(255,212,0,0.22)',
  shadow: '#000000',
  radius: 16,
};

const light: Theme = {
  bg: '#F5F7FA',
  surface: '#FFFFFF',
  surfaceAlt: '#EDF1F6',
  border: '#D3DBE4',
  text: '#0D1520',
  textDim: '#5A6875',
  accent: '#5A9E00',
  accentText: '#FFFFFF',
  accentSoft: 'rgba(90,158,0,0.12)',
  danger: '#C62828',
  onDanger: '#FFFFFF',
  dangerSoft: 'rgba(198,40,40,0.10)',
  ok: '#1B7F3B',
  okSoft: 'rgba(27,127,59,0.10)',
  warn: '#9A6700',
  warnSoft: 'rgba(154,103,0,0.10)',
  shadow: '#28323D',
  backdrop: 'rgba(13,21,32,0.60)',
  radius: 16,
};

const lightHighContrast: Theme = {
  ...light,
  bg: '#FFFFFF',
  surface: '#FFFFFF',
  surfaceAlt: '#F0F0F0',
  border: '#000000',
  text: '#000000',
  textDim: '#1A1A1A',
  accent: '#0033CC',
  accentText: '#FFFFFF',
  accentSoft: 'rgba(0,51,204,0.10)',
};

export function pickTheme(darkMode: boolean, highContrast: boolean): Theme {
  if (darkMode) return highContrast ? darkHighContrast : dark;
  return highContrast ? lightHighContrast : light;
}

/**
 * Shared spacing scale — every screen pulls gaps from here so padding never drifts
 * between tabs.
 */
export const SPACE = {
  xs: 4,
  sm: 8,
  md: 14,
  lg: 20,
  xl: 28,
} as const;

/** Card shadow recipe: shadowColor={theme.shadow} then spread this. */
export const elevation = {
  shadowOpacity: 0.14,
  shadowRadius: 10,
  shadowOffset: { width: 0, height: 4 },
  elevation: 2,
} as const;

/** Font sizes scale with the user's uiScale preference — this app is used by low-vision people. */
export function scaled(base: number, uiScale: number): number {
  const scale = Number.isFinite(uiScale) ? Math.min(2.0, Math.max(0.8, uiScale)) : 1;
  return Math.round(base * scale);
}
