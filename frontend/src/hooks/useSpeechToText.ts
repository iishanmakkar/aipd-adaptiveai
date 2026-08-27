import { useCallback, useState } from 'react';
import { apiService } from '../services/api';
import { mockApi } from '../services/mockApi';
import type { TranscribeResponse } from '../types/api';

const USE_MOCK_API = import.meta.env.VITE_USE_MOCK === 'true';

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
      let response: TranscribeResponse;
      
      if (USE_MOCK_API) {
        response = await mockApi.transcribe();
      } else {
        response = await apiService.transcribe(audioBlob);
      }
      
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