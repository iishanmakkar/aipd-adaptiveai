import { useCallback } from 'react';
import { apiService } from '../services/api';

export function useBehaviorTracking(sessionId: string | null) {
  const recordEvent = useCallback(async (
    eventType: 'replay' | 'skip' | 'listen',
    listenTime?: number
  ) => {
    if (!sessionId) return;
    try {
      await apiService.recordBehaviorEvent({
        session_id: sessionId,
        event_type: eventType,
        listen_time: listenTime,
      });
    } catch (err) {
      console.warn('Behavior event recording failed:', err);
    }
  }, [sessionId]);

  const recordReplay = useCallback(() => recordEvent('replay'), [recordEvent]);
  const recordSkip = useCallback(() => recordEvent('skip'), [recordEvent]);
  const recordListen = useCallback((listenTime: number) => recordEvent('listen', listenTime), [recordEvent]);

  return { recordReplay, recordSkip, recordListen };
}

// Extend apiService with recordBehaviorEvent
// This will be added to api.ts