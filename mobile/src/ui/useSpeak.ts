import { useCallback } from 'react';

import { assist, assistAvailable } from '../native/assist';
import { useSettings } from '../services/profile';

/**
 * One shared "say it out loud" hook for every screen.
 *
 * The app is built for blind users, so a result that is only rendered as text or
 * shown in an Alert is a result they never receive. Every screen should route
 * its feedback through this hook so responses are spoken consistently.
 *
 * Returns a no-op when the user has turned "Speak responses" off or when the
 * native TTS module is unavailable, and never rejects.
 */
export function useSpeak(): (text: string) => void {
  const settings = useSettings();

  return useCallback(
    (text: string) => {
      if (!settings.speakResponses || !assistAvailable || !text) return;
      void assist.speak(text, settings.speechRate, settings.language).catch(() => {});
    },
    [settings.speakResponses, settings.speechRate, settings.language],
  );
}
