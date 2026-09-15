export interface QueryRequest {
  session_id: string;
  input_text: string;
  input_source: 'voice' | 'text';
  screen_context: string;
}

export interface QueryResponse {
  response_text: string;
  agent_used: string;
  suggested_action: string | null;
  confidence: number;
  /** Knowledge-base ids that grounded this answer (RAG sources). */
  sources_used?: string[];
}

export interface TranscribeRequest {
  audio: Blob;
}

export interface TranscribeResponse {
  transcript: string;
}

export interface SessionRequest {
  user_id?: string;
}

export interface SessionResponse {
  session_id: string;
}

export interface SessionSummary {
  session_id: string;
  created_at: string;
  message_count: number;
}

export interface SessionListResponse {
  sessions: SessionSummary[];
  total: number;
}

export type Verbosity = 'concise' | 'standard' | 'detailed';
export type DisabilityProfile = 'none' | 'blind' | 'low_vision' | 'cognitive' | 'motor';
export type LanguageComplexity = 'simple' | 'standard' | 'technical';

export interface PreferenceResponse {
  verbosity_level: Verbosity;
  voice_speed: number;
  disability_profile: DisabilityProfile;
  language_complexity: LanguageComplexity;
}

export interface PreferenceUpdate {
  verbosity_level: Verbosity;
  voice_speed: number;
  disability_profile: DisabilityProfile;
  language_complexity: LanguageComplexity;
}

/**
 * One message row as the backend's GET /api/history actually returns it:
 * `created_at` is an ISO string on the wire (Message.timestamp is a Date only
 * after useSession normalizes it - feeding the raw row to the UI crashed
 * MessageBubble's Date calls).
 */
export interface HistoryMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  agent_used?: string | null;
  created_at: string;
}

export interface HistoryResponse {
  session_id: string;
  messages: HistoryMessage[];
  total: number;
  page: number;
  page_size: number;
}

export interface VLMRequest {
  model: string;
  messages: VLMMessage[];
  max_tokens?: number;
  temperature?: number;
}

export interface VLMMessage {
  role: 'user' | 'assistant' | 'system';
  content: string | VLMContent[];
}

export interface VLMContent {
  type: 'text' | 'image_url';
  text?: string;
  image_url?: {
    url: string;
  };
}

export interface VLMResponse {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: VLMChoice[];
  usage: VLMUsage;
}

export interface VLMChoice {
  index: number;
  message: {
    role: string;
    content: string;
  };
  finish_reason: string;
}

export interface VLMUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}