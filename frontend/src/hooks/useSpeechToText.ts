import { useCallback, useState } from 'react';
import { apiService } from '../services/api';
import type { TranscribeResponse } from '../types/api';

interface UseSpeechToTextReturn {
  transcribe: (audioBlob: Blob) => Promise<string>;
  isTranscribing: boolean;
  error: string | null;
}

export function useSpeechToText(): UseSpeechToTextReturn {
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const transcribe = useCallback(async (audioBlob: Blob): Promise<string> => {
    setIsTranscribing(true);
    setError(null);

    try {
      const response: TranscribeResponse = await apiService.transcribe(audioBlob);
      return response.transcript;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Transcription failed';
      setError(message);
      throw err;
    } finally {
      setIsTranscribing(false);
    }
  }, []);

  return {
    transcribe,
    isTranscribing,
    error,
  };
}