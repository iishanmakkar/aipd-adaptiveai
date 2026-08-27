export interface QueryRequest {
  session_id: string;
  input_text: string;
  input_source: 'voice' | 'text';
  screen_context: string;
}

export interface QueryResponse {
  response_text: string;
  agent_used: string;
  suggested_action: string;
  confidence: number;
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

import type { Message } from './chat';

export interface HistoryResponse {
  messages: Message[];
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