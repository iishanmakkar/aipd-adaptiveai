import { useCallback, useState } from 'react';
import { apiService } from '../services/api';
import { fileToCompressedBase64, validateImageFile } from '../utils/image';

interface UseVisionModelReturn {
  describeImage: (file: File) => Promise<string>;
  isDescribing: boolean;
  error: string | null;
}

export function useVisionModel(): UseVisionModelReturn {
  const [isDescribing, setIsDescribing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const describeImage = useCallback(async (file: File): Promise<string> => {
    const validation = validateImageFile(file);
    if (!validation.valid) {
      throw new Error(validation.error);
    }

    setIsDescribing(true);
    setError(null);

    try {
      const base64 = await fileToCompressedBase64(file);
      return await apiService.describeImage(base64);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Image description failed';
      setError(message);
      throw err;
    } finally {
      setIsDescribing(false);
    }
  }, []);

  return {
    describeImage,
    isDescribing,
    error,
  };
}