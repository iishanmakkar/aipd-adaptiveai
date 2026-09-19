import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import type {
  QueryRequest, QueryResponse, TranscribeResponse, SessionResponse, HistoryResponse,
  SessionListResponse, PreferenceResponse, PreferenceUpdate, VLMRequest, VLMResponse,
  BehaviorEvent, PageContextResponse,
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
        console.log('[API] Request:', config.method?.toUpperCase(), config.url);
        return config;
      },
      (error) => Promise.reject(error)
    );

    this.client.interceptors.response.use(
      (response) => {
        console.log('[API] Response:', response.status, response.config.url);
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
    const response = await this.client.put<PreferenceResponse>('/api/preferences', prefs);
    return response.data;
  }

  async recordBehaviorEvent(event: BehaviorEvent): Promise<{ status: string }> {
    const response = await this.client.post<{ status: string }>('/api/behavior-event', event);
    return response.data;
  }

  async describeImage(imageBase64: string, prompt?: string): Promise<string> {
    const vlmUrl = import.meta.env.VITE_NIM_VLM_URL || 'http://localhost:8000/v1/chat/completions';
    const model = import.meta.env.VITE_NIM_VLM_MODEL || 'meta/llama-3.2-11b-vision-instruct';
    const apiKey = import.meta.env.VITE_NIM_API_KEY;

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
    if (apiKey) {
      headers['Authorization'] = `Bearer ${apiKey}`;
    }

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