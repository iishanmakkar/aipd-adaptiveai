export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  input_source?: 'voice' | 'text';
  agent_used?: string;
  suggested_action?: string;
  confidence?: number;
  screen_context?: string;
  is_loading?: boolean;
}

import type { AccessibilityPreferences } from './accessibility';

export interface Session {
  id: string;
  created_at: Date;
  messages: Message[];
  preferences: AccessibilityPreferences;
}

export type MessageRole = 'user' | 'assistant' | 'system';

export interface ChatState {
  messages: Message[];
  current_input: string;
  is_recording: boolean;
  is_processing: boolean;
  is_speaking: boolean;
  screen_context: string;
  session_id: string;
}