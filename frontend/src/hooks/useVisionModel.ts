import { useCallback, useState } from 'react';
import { apiService } from '../services/api';
import { mockApi } from '../services/mockApi';
import { fileToCompressedBase64, validateImageFile } from '../utils/image';

const USE_MOCK_API = import.meta.env.VITE_USE_MOCK === 'true';

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
      let description: string;
      
      if (USE_MOCK_API) {
        description = await mockApi.describeImage();
      } else {
        const base64 = await fileToCompressedBase64(file);
        description = await apiService.describeImage(base64);
      }
      
      return description;
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