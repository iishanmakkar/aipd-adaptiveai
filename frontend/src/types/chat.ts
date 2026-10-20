export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  input_source?: 'voice' | 'text';
  agent_used?: string;
  suggested_action?: string;
  confidence?: number;
  sources?: string[];
  screen_context?: string;
  is_loading?: boolean;
}
