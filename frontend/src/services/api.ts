import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import type {
  QueryRequest, QueryResponse, TranscribeResponse, SessionResponse, HistoryResponse,
  SessionListResponse, PreferenceResponse, PreferenceUpdate, VLMRequest, VLMResponse,
  BehaviorEvent, PageContextResponse,
  MonitorStartResponse, MonitorStopResponse, MonitorEventsResponse,
} from '../types/api';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

class ApiService {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 30000,
    });

    this.client.interceptors.request.use(
      (config: InternalAxiosRequestConfig) => {
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.log('[API] Request:', config.method?.toUpperCase(), config.url);
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    this.client.interceptors.response.use(
      (response) => {
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.log('[API] Response:', response.status, response.config.url);
        }
        return response;
      },
      (error) => {
        console.error('[API] Error:', error.response?.status, error.message);
        return Promise.reject(error);
      }
    );
  }

  async query(request: QueryRequest): Promise<QueryResponse> {    // A real query spans intent classification + RAG retrieval + an NIM
    // completion, and NIM latency on this account varies from ~3s to ~90s+.
    // This must exceed the backend's worst case (45s intent + 90s agent +
    // 30s policy rewrite), otherwise the UI aborts a request still in flight.
    const response = await this.client.post<QueryResponse>('/api/query', request, {
      timeout: 180000,
    });
    return response.data;
  }

  async pageContext(url: string): Promise<PageContextResponse> {
    // Live Chromium load + snapshot + VLM description; can take ~30-60s.
    const response = await this.client.post<PageContextResponse>('/api/page-context', { url }, {
      timeout: 180000,
    });
    return response.data;
  }

  async transcribe(audioBlob: Blob): Promise<TranscribeResponse> {
    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');

    const response = await this.client.post<TranscribeResponse>('/api/transcribe', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      // CPU whisper on a 30-second recording can take a while; the 30s default
      // aborted legitimate transcriptions.
      timeout: 90000,
    });
    return response.data;
  }

  async createSession(userId?: string): Promise<SessionResponse> {
    const response = await this.client.post<SessionResponse>('/api/session', { user_id: userId });
    return response.data;
  }

  async getHistory(sessionId: string): Promise<HistoryResponse> {
    const response = await this.client.get<HistoryResponse>(`/api/history/${sessionId}`);
    return response.data;
  }

  async listSessions(): Promise<SessionListResponse> {
    const response = await this.client.get<SessionListResponse>('/api/sessions');
    return response.data;
  }

  async getPreferences(): Promise<PreferenceResponse> {
    const response = await this.client.get<PreferenceResponse>('/api/preferences');
    return response.data;
  }

  async updatePreferences(prefs: PreferenceUpdate): Promise<PreferenceResponse> {
    try {
      const response = await this.client.put<PreferenceResponse>('/api/preferences', prefs);
      return response.data;
    } catch (err) {
      // Offline (no response at all): queue the mutation for the
      // online-drain in main.tsx. A 4xx is a bad payload, not an outage —
      // queueing it would poison the drain, so rethrow.
      if (axios.isAxiosError(err) && !err.response) {
        const { enqueueMutation } = await import('../utils/offlineQueue');
        await enqueueMutation({ url: '/api/preferences', method: 'PUT', body: prefs });
      }
      throw err;
    }
  }

  async recordBehaviorEvent(event: BehaviorEvent): Promise<{ status: string }> {
    try {
      const response = await this.client.post<{ status: string }>('/api/behavior-event', event);
      return response.data;
    } catch (err) {
      // Behavior signals are advisory: a dead network queues them for the
      // online-drain; a 4xx means the event itself is invalid, so drop it.
      // Either way chat continues — recording must never break answers.
      if (axios.isAxiosError(err) && !err.response) {
        try {
          const { enqueueMutation } = await import('../utils/offlineQueue');
          await enqueueMutation({ url: '/api/behavior-event', method: 'POST', body: event });
        } catch {
          /* IndexedDB unavailable - signal is lost, chat continues */
        }
        return { status: 'queued' };
      }
      return { status: 'dropped' };
    }
  }

  // ---- Round 9: real-time page monitoring (explicit consent in, one-action out).

  async monitorStart(sessionId: string): Promise<MonitorStartResponse> {
    const response = await this.client.post<MonitorStartResponse>('/api/monitor/start', {
      session_id: sessionId,
    }, { timeout: 45000 });
    return response.data;
  }

  async monitorStop(sessionId: string): Promise<MonitorStopResponse> {
    const response = await this.client.post<MonitorStopResponse>('/api/monitor/stop', {
      session_id: sessionId,
    }, { timeout: 45000 });
    return response.data;
  }

  async monitorEvents(sessionId: string): Promise<MonitorEventsResponse> {
    // No `since`: delivery is owned server-side (cursor in SharedDict); the
    // client cannot rewind it.
    const response = await this.client.get<MonitorEventsResponse>(
      `/api/monitor/events?session_id=${encodeURIComponent(sessionId)}`, {
        timeout: 45000,
      });
    return response.data;
  }

  async describeImage(imageBase64: string, prompt?: string): Promise<string> {
    // Vision always goes through the backend proxy, which injects NIM_API_KEY
    // server-side. Never send a key from here: any VITE_* var bakes into the
    // public JS bundle.
    const vlmUrl = import.meta.env.VITE_NIM_VLM_URL || 'http://localhost:8000/v1/chat/completions';
    const model = import.meta.env.VITE_NIM_VLM_MODEL || 'meta/llama-3.2-11b-vision-instruct';

    const request: VLMRequest = {
      model,
      messages: [
        {
          role: 'user',
          content: [
            {
              type: 'text',
              text: prompt || 'Describe this screenshot for a visually impaired user. Identify form fields, buttons, layout, and any visible text. Be concise but thorough.',
            },
            {
              type: 'image_url',
              image_url: {
                url: `data:image/jpeg;base64,${imageBase64}`,
              },
            },
          ],
        },
      ],
      max_tokens: 500,
      temperature: 0.3,
    };

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    // Backend VLM proxy allows 60s; stay above it so the caller sees the
    // upstream result (or its error) rather than a local abort.
    const response = await axios.post<VLMResponse>(vlmUrl, request, { headers, timeout: 90000 });
    
    const content = response.data.choices[0]?.message?.content;
    if (!content) {
      throw new Error('No description returned from VLM');
    }
    return content;
  }
}

export const apiService = new ApiService();