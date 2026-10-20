import axios from 'axios';
import type { AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import { expireSession, getToken } from '../utils/auth';
import type {
  QueryRequest, QueryResponse, TranscribeResponse, SessionResponse, HistoryResponse,
  SessionListResponse, PreferenceResponse, PreferenceUpdate, VLMRequest, VLMResponse,
  BehaviorEvent, PageContextResponse,
  MonitorStartResponse, MonitorStopResponse, MonitorEventsResponse,
  TokenResponse, MeResponse, ShareCreateResponse, SharedSessionResponse,
  BrailleResponse, FormFillResult,
} from '../types/api';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

/** Only the sign-in attempts themselves answer 401 about the attempt: /auth/me
 * failing means the *token* is dead, and exempting it leaves the user on the
 * chat UI with a live-looking session until some other call happens to 401. */
function isAuthCall(url?: string): boolean {
  return !!url && (url.startsWith('/auth/login') || url.startsWith('/auth/register'));
}

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
        const token = getToken();
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
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
        const status = error.response?.status;
        console.error('[API] Error:', status, error.message);
        // A rejected token is not this user's session any more (expiry, secret
        // rotation, deleted account). Drop it once so the app shows the login
        // screen instead of failing every later call the same way. Signing in
        // is exempt: a wrong password is a 401 about that attempt, not a dead
        // session.
        if (status === 401 && !isAuthCall(error.config?.url)) {
          expireSession();
        }        return Promise.reject(error);
      }
    );
  }

  // ---- Account ----

  async register(email: string, password: string): Promise<TokenResponse> {
    const response = await this.client.post<TokenResponse>('/auth/register', { email, password });
    return response.data;
  }

  async login(email: string, password: string): Promise<TokenResponse> {
    const response = await this.client.post<TokenResponse>('/auth/login', { email, password });
    return response.data;
  }

  async me(): Promise<MeResponse> {
    const response = await this.client.get<MeResponse>('/auth/me');
    return response.data;
  }

  async deleteAccount(): Promise<void> {
    await this.client.delete('/auth/account');
  }

  async createShare(sessionId: string): Promise<ShareCreateResponse> {
    const response = await this.client.post<ShareCreateResponse>('/api/share', {
      session_id: sessionId,
    });
    return response.data;
  }

  /** Caregiver side: the token in the URL is the whole credential, so this must
   * go out without the owner's bearer even when the owner is signed in. */
  async watchShare(token: string): Promise<SharedSessionResponse> {
    const response = await axios.get<SharedSessionResponse>(
      `${API_BASE_URL}/api/share/${encodeURIComponent(token)}`, { timeout: 30000 });
    return response.data;
  }

  /** Returns {status, total} — the backend's actual reply (the declared
   * ShareAnnotation {text, ts} was never what this endpoint returns). */
  async annotateShare(token: string, text: string): Promise<{ status: string; total: number }> {
    const response = await axios.post<{ status: string; total: number }>(
      `${API_BASE_URL}/api/share/${encodeURIComponent(token)}/annotate`,
      { text }, { headers: { 'Content-Type': 'application/json' }, timeout: 30000 });
    return response.data;
  }

  async braille(text: string): Promise<BrailleResponse> {
    const response = await this.client.get<BrailleResponse>('/api/alt/braille', {
      params: { text },
    });
    return response.data;
  }

  async formFill(url: string, values: Record<string, string>, replay = false): Promise<FormFillResult> {
    // Live Chromium: discover, cache and fill; a heal pass adds another round.
    // Pre-validate the backend's bounds client-side (100 pairs, 2000 chars)
    // so a huge form fails here with a message instead of a bare 422.
    const keys = Object.keys(values);
    if (keys.length > 100) {
      throw new Error(`Too many fields to fill at once (${keys.length}; max 100).`);
    }
    const trimmed: Record<string, string> = {};
    for (const key of keys) {
      const value = values[key] ?? '';
      trimmed[key.slice(0, 200)] = value.length > 2000
        ? value.slice(0, 2000)
        : value;
    }
    const response = await this.client.post<FormFillResult>('/api/form-fill',
      { url, values: trimmed, replay }, { timeout: 180000 });
    return response.data;
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
    // Client-side guards with spoken-friendly errors, before the 90s upload:
    // an empty recording and an over-10MB blob both fail server-side anyway.
    if (audioBlob.size === 0) {
      throw new Error('Nothing was recorded - please try again.');
    }
    if (audioBlob.size > 10 * 1024 * 1024) {
      throw new Error('That recording is too long to send (over 10 MB). Try a shorter one.');
    }
    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');

    const response = await this.client.post<TranscribeResponse>('/api/transcribe', formData, {
      // Let axios set multipart boundary from FormData (explicit header breaks it).
      // CPU whisper on a 30-second recording can take a while; the 30s default
      // aborted legitimate transcriptions.
      timeout: 90000,
    });
    return response.data;
  }

  async createSession(): Promise<SessionResponse> {
    const response = await this.client.post<SessionResponse>('/api/session', {});
    return response.data;
  }

  async getHistory(sessionId: string, page = 1, pageSize = 20): Promise<HistoryResponse> {
    const response = await this.client.get<HistoryResponse>(`/api/history/${sessionId}`, {
      params: { page, page_size: pageSize },
    });
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
      // queueing it would poison the drain, so rethrow. Timeouts may have
      // committed server-side: never queue blindly (see apiError).
      const { isOfflineError } = await import('../utils/apiError');
      if (isOfflineError(err)) {
        try {
          const { enqueueMutation } = await import('../utils/offlineQueue');
          await enqueueMutation({ url: '/api/preferences', method: 'PUT', body: prefs });
        } catch {
          /* IndexedDB unavailable - fall through to throw */
        }
      }
      throw err;
    }
  }

  async recordBehaviorEvent(event: BehaviorEvent): Promise<{ status: string; replay_count?: number; skip_count?: number }> {
    try {
      const response = await this.client.post<{ status: string; replay_count?: number; skip_count?: number }>('/api/behavior-event', event);
      return response.data;
    } catch (err) {
      // Behavior signals are advisory: a dead network queues them for the
      // online-drain; a 4xx means the event itself is invalid, so rethrow
      // instead of reporting a 'dropped' success the caller reads as handled.
      const { isOfflineError } = await import('../utils/apiError');
      if (isOfflineError(err)) {
        try {
          const { enqueueMutation } = await import('../utils/offlineQueue');
          await enqueueMutation({ url: '/api/behavior-event', method: 'POST', body: event });
        } catch {
          /* IndexedDB unavailable - signal is lost, chat continues */
        }
        return { status: 'queued' };
      }
      throw err;
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
    // public JS bundle. The proxy URL defaults to this same API origin (not a
    // hardcoded localhost, which breaks every non-localhost deployment).
    const apiBase = API_BASE_URL.replace(/\/$/, '');
    const vlmUrl = import.meta.env.VITE_NIM_VLM_URL || `${apiBase}/v1/chat/completions`;
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
    if (typeof content === 'string') return content;
    return content.map((p) => p.text ?? '').join(' ');
  }
}

export const apiService = new ApiService();