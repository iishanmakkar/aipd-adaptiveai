import { useCallback, useState } from 'react';
import { apiService } from '../services/api';
import type { QueryRequest, QueryResponse } from '../types/api';

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
      return await apiService.query(request);
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