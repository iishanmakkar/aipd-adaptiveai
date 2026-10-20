import { useCallback, useRef, useState } from 'react';
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
  // Latest-call-wins: without this, the first of two overlapping queries to
  // finish cleared isQuerying (and set its error) while the second was still
  // in flight, leaving the UI quiescent mid-answer.
  const latestRef = useRef(0);

  const sendQuery = useCallback(async (request: QueryRequest): Promise<QueryResponse> => {
    const callId = latestRef.current + 1;
    latestRef.current = callId;
    setIsQuerying(true);
    setError(null);

    try {
      return await apiService.query(request);
    } catch (err) {
      if (latestRef.current === callId) {
        const message = err instanceof Error ? err.message : 'Query failed';
        setError(message);
      }
      throw err;
    } finally {
      if (latestRef.current === callId) {
        setIsQuerying(false);
      }
    }
  }, []);

  return {
    sendQuery,
    isQuerying,
    error,
  };
}