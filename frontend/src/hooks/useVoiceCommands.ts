import { useCallback, useEffect, useState } from 'react';

export interface VoiceCommand {
  pattern: RegExp;
  label: string;
  action: string;
}

export const VOICE_COMMANDS: VoiceCommand[] = [
  { pattern: /\bgo back\b/i, action: 'go-back', label: 'Go back' },
  { pattern: /\bread (that|this) again\b/i, action: 'replay', label: 'Read that again' },
  { pattern: /\b(bigger text|increase font|larger text)\b/i, action: 'bigger-text', label: 'Bigger text' },
  { pattern: /\b(high contrast|contrast)\b/i, action: 'toggle-contrast', label: 'High contrast' },
  { pattern: /\bwatch my screen\b/i, action: 'monitor-start', label: 'Watch my screen' },
  { pattern: /\bstop watching\b/i, action: 'monitor-stop', label: 'Stop watching' },
  { pattern: /\bnew session\b/i, action: 'new-session', label: 'New session' },
];

export function matchVoiceCommand(transcript: string): string | null {
  for (const cmd of VOICE_COMMANDS) {
    if (cmd.pattern.test(transcript)) return cmd.action;
  }
  return null;
}

/**
 * Phase 3.2 — voice-first navigation: transcript -> action, plus Cmd+K palette.
 * The host component passes handlers; this hook owns matching + palette state.
 */
export function useVoiceCommands(handlers: Record<string, () => void>) {
  const [paletteOpen, setPaletteOpen] = useState(false);

  const handleTranscript = useCallback(
    (transcript: string): boolean => {
      const action = matchVoiceCommand(transcript);
      if (action && handlers[action]) {
        handlers[action]();
        return true;
      }
      return false;
    },
    [handlers],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
      if (e.key === 'Escape') setPaletteOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return { paletteOpen, setPaletteOpen, handleTranscript, commands: VOICE_COMMANDS };
}
