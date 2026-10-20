export interface QueryRequest {
  session_id: string;
  input_text: string;
  input_source: 'voice' | 'text';
  screen_context: string;
  unified_context?: UnifiedContext;
  /** Phase 2.1: route via /agent/orchestrate instead of the single target agent. */
  autonomous?: boolean;
}

/** Phase 2.2 — fused multimodal context (replaces bare screen_ctx string).
 * Behavior travels separately via POST /api/behavior-event (the dedicated
 * intake the policy engine reads); it is deliberately not a field here. */
export interface UnifiedContext {
  screen_text: string;
  dom_snapshot: string;
  screenshot_b64?: string;
  vlm_description?: string;
  user_intent?: string;
  disability_profile: DisabilityProfile;
}

export interface QueryResponse {
  response_text: string;
  agent_used: string;
  suggested_action: string | null;
  confidence: number;
  /** Knowledge-base ids that grounded this answer (RAG sources). */
  sources_used?: string[];
}

export interface TranscribeResponse {
  transcript: string;
  language?: string;
  duration?: number;
}

export interface SessionResponse {
  session_id: string;
  created_at: string;
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
  verbosity_level?: Verbosity;
  voice_speed?: number;
  disability_profile?: DisabilityProfile;
  language_complexity?: LanguageComplexity;
}

/** Behavior event sent from frontend to backend for adaptive policy tracking. */
export interface BehaviorEvent {
  session_id: string;
  event_type: 'replay' | 'skip' | 'listen';
  listen_time?: number;
}

/** Live page context: what the backend's Chromium actually saw at a URL. */
export interface PageField {
  label: string;
  type: string;
  required: boolean;
}

export interface PageContextResponse {
  url: string;
  http_status: number | null;
  title: string;
  field_count: number;
  fields: PageField[];
  description: string;
}

/**
 * One message row as the backend's GET /api/history actually returns it:
 * `created_at` is an ISO string on the wire (Message.timestamp is a Date only
 * after useSession normalizes it - feeding the raw row to the UI crashed
 * MessageBubble's Date calls).
 */
export interface HistoryMessage {
  id: string;
  role: 'user' | 'assistant';
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
    content: string | Array<{ type: string; text?: string }>;
  };
  finish_reason: string;
}

export interface VLMUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

/** Round 9: real-time page monitoring. */
export interface MonitorStartResponse {
  active: boolean;
  status: string;
  message?: string;
}

export interface MonitorStopResponse {
  active: boolean;
  status: string;
  stats?: MonitorStats;
}

export interface MonitorCounters {
  polls: number;
  polls_idle: number;
  baseline_polls: number;
  raw_activity: number;
  changes_detected: number;
  minor_ignored: number;
  deferred_by_quiet: number;
  rate_blocked: number;
  nim_calls: number;
  narrations: number;
  errors: number;
}

export interface MonitorStats {
  session_id?: string;
  active?: boolean;
  counters?: MonitorCounters;
}

export interface NarrationEvent {
  id: number;
  ts: number;
  text: string;
}

export interface MonitorEventsResponse {
  active: boolean;
  narrations: NarrationEvent[];
  cursor: number;
  stats: MonitorStats;
}

/** Auth: the backend issues a bearer JWT; every /api call carries it. */
export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface MeResponse {
  id: string;
  email: string;
}

/** Phase 4.2: caregiver share link + read-only transcript. */
export interface ShareCreateResponse {
  share_token: string;
  watch_url: string;
  expires_in_seconds: number;
}

export interface ShareAnnotation {
  text: string;
  ts: number;
}

export interface SharedSessionResponse {
  session_id: string;
  messages: { role: string; content: string }[];
  annotations: ShareAnnotation[];
  read_only: boolean;
}

/** Phase 4.3: braille shaping of one answer.
 * `lines`: shaped plain text for a refreshable display;
 * `grade1`: real uncontracted Grade-1 Unicode braille (not Grade 2). */
export interface BrailleResponse {
  lines: string[];
  grade1: string[];
  preview_braille: string;
}

/** POST /api/form-fill: per-action truth from a real Chromium. */
export interface FormFillResult {
  status: string;
  action: string;
  episode_id?: string | null;
  discovery_id?: string;
  new_episode?: boolean;
  reason?: string;
  url?: string;
  success_count: number;
  failure_count: number;
  unfilled?: string[];
  page_message?: string;
  replay_results?: {
    status: string;
    action?: string;
    field_id?: string;
    label?: string;
    value?: string;
    reason?: string;
  }[];
  healed?: {
    status: string;
    repaired_fields?: number;
    stale_fields?: number;
    repairs?: { label: string; old_selector: string; new_selector: string }[];
  };
}