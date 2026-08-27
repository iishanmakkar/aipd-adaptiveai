import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import type { QueryRequest, QueryResponse, TranscribeResponse, SessionResponse, HistoryResponse, VLMRequest, VLMResponse } from '../types/api';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const MOCK_API_URL = import.meta.env.VITE_MOCK_API_URL || 'http://localhost:3001';
const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

class ApiService {
  private client: AxiosInstance;
  private mockClient: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 30000,
    });

    this.mockClient = axios.create({
      baseURL: MOCK_API_URL,
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 10000,
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

  private getClient() {
    return USE_MOCK ? this.mockClient : this.client;
  }

  async query(request: QueryRequest): Promise<QueryResponse> {
    const response = await this.getClient().post<QueryResponse>('/api/query', request);
    return response.data;
  }

  async transcribe(audioBlob: Blob): Promise<TranscribeResponse> {
    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');
    
    const response = await this.getClient().post<TranscribeResponse>('/api/transcribe', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  }

  async createSession(userId?: string): Promise<SessionResponse> {
    const response = await this.getClient().post<SessionResponse>('/api/session', { user_id: userId });
    return response.data;
  }

  async getHistory(sessionId: string): Promise<HistoryResponse> {
    const response = await this.getClient().get<HistoryResponse>(`/api/history/${sessionId}`);
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

    const response = await axios.post<VLMResponse>(vlmUrl, request, { headers, timeout: 60000 });
    
    const content = response.data.choices[0]?.message?.content;
    if (!content) {
      throw new Error('No description returned from VLM');
    }
    return content;
  }
}

export const apiService = new ApiService();