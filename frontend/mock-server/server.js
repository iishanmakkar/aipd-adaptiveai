const express = require('express');
const cors = require('cors');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3001;
const MOCK_DELAY = parseInt(process.env.MOCK_DELAY_MS || '800', 10);

app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));

// Request logging
app.use((req, res, next) => {
  console.log(`[MOCK] ${req.method} ${req.path}`);
  next();
});

// Helper to simulate delay
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

// Mock data
const mockSessions = new Map();
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

const mockResponses = {
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

function pickMockResponse(inputText) {
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

// POST /api/query
app.post('/api/query', async (req, res) => {
  await delay(MOCK_DELAY);
  
  const { session_id, input_text, input_source, screen_context } = req.body;
  
  if (!session_id || !input_text) {
    return res.status(400).json({ error: 'session_id and input_text are required' });
  }
  
  const response = pickMockResponse(input_text);
  
  // Store in session history
  if (!mockSessions.has(session_id)) {
    mockSessions.set(session_id, []);
  }
  const history = mockSessions.get(session_id);
  history.push({
    id: `msg-${Date.now()}`,
    role: 'user',
    content: input_text,
    timestamp: new Date().toISOString(),
    input_source: input_source || 'text',
    screen_context,
  });
  history.push({
    id: `msg-${Date.now() + 1}`,
    role: 'assistant',
    content: response.response_text,
    timestamp: new Date().toISOString(),
    agent_used: response.agent_used,
    suggested_action: response.suggested_action,
    confidence: response.confidence,
  });
  
  res.json(response);
});

// POST /api/transcribe
app.post('/api/transcribe', async (req, res) => {
  await delay(500);
  
  // In real implementation, this would process the audio file
  // For mock, return a random transcript
  const transcript = mockTranscripts[Math.floor(Math.random() * mockTranscripts.length)];
  
  res.json({ transcript });
});

// POST /api/session
app.post('/api/session', async (req, res) => {
  await delay(200);
  
  const sessionId = `session-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  mockSessions.set(sessionId, []);
  
  res.json({ session_id: sessionId });
});

// GET /api/history/:sessionId
app.get('/api/history/:sessionId', async (req, res) => {
  await delay(200);
  
  const { sessionId } = req.params;
  const history = mockSessions.get(sessionId) || [];
  
  res.json({ messages: history });
});

// POST /v1/chat/completions (Mock NVIDIA NIM VLM)
app.post('/v1/chat/completions', async (req, res) => {
  await delay(1500);
  
  const { messages } = req.body;
  
  // Check if image is in the request
  const hasImage = messages?.some(msg => 
    Array.isArray(msg.content) && msg.content.some(c => c.type === 'image_url')
  );
  
  if (!hasImage) {
    return res.status(400).json({ error: 'Image required for VLM' });
  }
  
  // Return mock description
  const descriptions = [
    "Screenshot shows a web form with fields: Full Name (text input), Date of Birth (date picker), Permanent Address (textarea), Aadhar Number (number input), and a Submit button. The form has a clean white background with blue labels.",
    "Image displays a government service portal with navigation menu on left, main content area showing a document upload section with drag-and-drop zone, and a footer with help links.",
    "Screenshot of an educational webpage showing a diagram of the water cycle with labeled stages: evaporation, condensation, precipitation, and collection. Text explanation below the diagram.",
    "Image shows a login page with email and password fields, a 'Remember me' checkbox, 'Forgot password' link, and a Sign In button. Background has a subtle gradient pattern.",
  ];
  
  const description = descriptions[Math.floor(Math.random() * descriptions.length)];
  
  res.json({
    id: `chatcmpl-${Date.now()}`,
    object: 'chat.completion',
    created: Math.floor(Date.now() / 1000),
    model: 'meta/llama-3.2-11b-vision-instruct',
    choices: [{
      index: 0,
      message: {
        role: 'assistant',
        content: description,
      },
      finish_reason: 'stop',
    }],
    usage: {
      prompt_tokens: 150,
      completion_tokens: 80,
      total_tokens: 230,
    },
  });
});

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Start server
app.listen(PORT, () => {
  console.log(`🚀 Mock server running on http://localhost:${PORT}`);
  console.log(`   POST /api/query - Main query endpoint`);
  console.log(`   POST /api/transcribe - Speech to text`);
  console.log(`   POST /api/session - Create session`);
  console.log(`   GET  /api/history/:id - Get history`);
  console.log(`   POST /v1/chat/completions - VLM endpoint`);
  console.log(`   Mock delay: ${MOCK_DELAY}ms`);
});