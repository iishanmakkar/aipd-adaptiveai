import type { QueryResponse, TranscribeResponse, SessionResponse, HistoryResponse } from '../types/api';
import type { Message } from '../types/chat';

const MOCK_DELAY = parseInt(import.meta.env.VITE_MOCK_DELAY_MS || '800', 10);

const mockSessions: Record<string, Message[]> = {};

const mockTranscripts = [
  "What is this field asking for?",
  "Help me fill out this form",
  "What does this button do?",
  "Read me the document",
  "Explain this webpage",
  "Simplify this concept",
  "What is the permanent address field?",
  "How do I navigate this page?",
];

const mockResponses: Record<string, QueryResponse> = {
  form_help: {
    response_text: "This field is asking for your permanent address as listed on your government ID proof. This is not your current residence address, but the address where you receive official mail.",
    agent_used: "form_agent",
    suggested_action: "highlight_field",
    confidence: 0.92,
  },
  document_help: {
    response_text: "The document appears to be a university admission form. It contains sections for personal information, educational background, and declaration. Would you like me to read a specific section?",
    agent_used: "document_agent",
    suggested_action: "none",
    confidence: 0.88,
  },
  web_navigation_help: {
    response_text: "This button labeled 'Submit Application' will send your completed form to the server. Make sure all required fields are filled before clicking. The button is currently enabled.",
    agent_used: "web_agent",
    suggested_action: "highlight_button",
    confidence: 0.9,
  },
  education_help: {
    response_text: "Photosynthesis is the process by which plants convert sunlight, carbon dioxide, and water into glucose and oxygen. Think of it as plants making their own food using sunlight as energy.",
    agent_used: "education_agent",
    suggested_action: "none",
    confidence: 0.85,
  },
  general_query: {
    response_text: "I'm here to help you with forms, documents, web navigation, and learning. What would you like assistance with today?",
    agent_used: "general_agent",
    suggested_action: "none",
    confidence: 0.75,
  },
};

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function pickMockResponse(inputText: string): QueryResponse {
  const lower = inputText.toLowerCase();
  
  if (lower.includes('field') || lower.includes('form') || lower.includes('address') || lower.includes('fill')) {
    return mockResponses.form_help;
  }
  if (lower.includes('document') || lower.includes('read') || lower.includes('pdf') || lower.includes('text')) {
    return mockResponses.document_help;
  }
  if (lower.includes('button') || lower.includes('navigat') || lower.includes('click') || lower.includes('link') || lower.includes('page')) {
    return mockResponses.web_navigation_help;
  }
  if (lower.includes('explain') || lower.includes('what is') || lower.includes('concept') || lower.includes('learn') || lower.includes('simplify')) {
    return mockResponses.education_help;
  }
  
  return mockResponses.general_query;
}

export const mockApi = {
  async query(request: { session_id: string; input_text: string; input_source: string; screen_context: string }): Promise<QueryResponse> {
    await delay(MOCK_DELAY);
    return pickMockResponse(request.input_text);
  },

  async transcribe(): Promise<TranscribeResponse> {
    await delay(500);
    const transcript = mockTranscripts[Math.floor(Math.random() * mockTranscripts.length)];
    return { transcript };
  },

  async createSession(): Promise<SessionResponse> {
    await delay(200);
    const sessionId = `session-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    mockSessions[sessionId] = [];
    return { session_id: sessionId };
  },

  async getHistory(sessionId: string): Promise<HistoryResponse> {
    await delay(200);
    return { messages: mockSessions[sessionId] || [] };
  },

  async describeImage(): Promise<string> {
    await delay(1500);
    return "Screenshot shows a web form with fields: Full Name (text input), Date of Birth (date picker), Permanent Address (textarea), Aadhar Number (number input), and a Submit button. The form has a clean white background with blue labels.";
  },
};