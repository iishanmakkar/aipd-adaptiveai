import { useCallback, useState } from 'react';
import { apiService } from '../services/api';
import { mockApi } from '../services/mockApi';
import type { QueryRequest, QueryResponse } from '../types/api';

const USE_MOCK_API = import.meta.env.VITE_USE_MOCK === 'true';

interface UseApiQueryReturn {
  sendQuery: (request: QueryRequest) => Promise<QueryResponse>;
  isQuerying: boolean;
  error: string | null;
}

export function useApiQuery(): UseApiQueryReturn {
  const [isQuerying, setIsQuerying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendQuery = useCallback(async (request: QueryRequest): Promise<QueryResponse> => {
    setIsQuerying(true);
    setError(null);

    try {
      let response: QueryResponse;
      
      if (USE_MOCK_API) {
        response = await mockApi.query(request);
      } else {
        response = await apiService.query(request);
      }
      
      return response;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Query failed';
      setError(message);
      throw err;
    } finally {
      setIsQuerying(false);
    }
  }, []);

  return {
    sendQuery,
    isQuerying,
    error,
  };
}