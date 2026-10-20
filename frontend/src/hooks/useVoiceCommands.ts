import { useCallback, useEffect, useState } from 'react';

export interface VoiceCommand {
  pattern: RegExp;
  label: string;
  action: string;
}

export const VOICE_COMMANDS: VoiceCommand[] = [
  { pattern: /\bgo back\b/i, action: 'go-back', label: 'Go back' },
  { pattern: /\b(read (that|this|it) again|repeat|say that again)\b/i, action: 'replay', label: 'Read that again' },
  { pattern: /\b(bigger text|increase font|larger text|make .* bigger|increase .* (font|text|size)|zoom in)\b/i, action: 'bigger-text', label: 'Bigger text' },
  { pattern: /\b(high contrast|contrast|turn on high contrast)\b/i, action: 'toggle-contrast', label: 'High contrast' },
  { pattern: /\bwatch (my|the) screen\b/i, action: 'monitor-start', label: 'Watch my screen' },
  { pattern: /\bstop watching( my| the)?( screen)?\b/i, action: 'monitor-stop', label: 'Stop watching' },
  { pattern: /\b((start |begin )?(a )?new session|start over|clear chat)\b/i, action: 'new-session', label: 'New session' },
  { pattern: /\b(fill this form|fill it|open form|start filling)\b/i, action: 'fill-form', label: 'Fill this form' },
  { pattern: /\b(submit form|submit it|send form|finish filling|fill the form)\b/i, action: 'submit-form', label: 'Submit form' },
  { pattern: /\b(close form|cancel filling|close dialog)\b/i, action: 'close-form', label: 'Close form' },
];

const ANCHORED = VOICE_COMMANDS.map((c) => ({ action: c.action, re: new RegExp(`^(?:${c.pattern.source})$`, 'i') }));

export function matchVoiceCommand(transcript: string): string | null {
  // Whole-utterance match (modulo a leading/trailing "please" and sentence
  // punctuation): substring matching ate real questions ("explain high
  // contrast in photos" toggled contrast; "I want to go back to school"
  // navigated away, losing the chat). A command must BE the utterance.
  // Punctuation stripped FIRST so "go back please." matches.
  const depunct = transcript.replace(/[.!?;:,()"…]+$/g, '').replace(/\s+/g, ' ').trim();
  const core = depunct.replace(/^(?:please\s+)?(.*?)(?:\s+please)?$/i, '$1').trim();
  for (const cmd of ANCHORED) {
    if (cmd.re.test(core)) return cmd.action;
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
      const target = e.target as HTMLElement | null;
      // Never hijack typing (or the browser's own address-bar shortcut):
      // Ctrl/Cmd+K inside any field must stay the field's.
      const inField = !!target?.closest?.('input,textarea,select,[contenteditable]');
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        if (inField) return;
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
      // Escape always closes the palette when it is open (even from its own
      // search field); it never touches anything else.
      if (e.key === 'Escape') setPaletteOpen((open) => (open ? false : open));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return { paletteOpen, setPaletteOpen, handleTranscript, commands: VOICE_COMMANDS };
}
