# AdaptiveAI Frontend + Voice + Vision

React + Vite frontend for the AdaptiveAI system — an accessible chat interface with voice input (Whisper STT), text-to-speech, and Vision-Language Model integration for screenshot understanding.

## Features

- **Accessible Chat UI**: ARIA labels, keyboard navigation, screen reader support
- **Voice Input**: Hold mic button → record → auto-transcribe via backend `/api/transcribe`
- **Text-to-Speech**: Auto-speaks responses using Web Speech API (browser native)
- **Screenshot Understanding**: Upload image → VLM describes it → used as context for queries
- **Accessibility Toolbar**: Font size (4 levels), high contrast mode, voice speed control
- **No mock layer**: the Express mock server and `mockApi.ts` were deleted; every request goes to the real backend

## Quick Start

```bash
# 1. Install dependencies
cd frontend
npm install

# 2. Start Vite dev server (needs backend on http://localhost:8000)
npm run dev
# Runs on http://localhost:5173
```

## Project Structure

```
frontend/
├── src/
│   ├── components/       # React components
│   │   ├── ChatInterface.tsx      # Main chat container
│   │   ├── MessageBubble.tsx      # Message display
│   │   ├── TextInput.tsx          # Text input with send
│   │   ├── MicButton.tsx          # Voice recording button
│   │   ├── ScreenshotUpload.tsx   # Image upload + preview
│   │   ├── StatusIndicator.tsx    # Listening/Thinking/Speaking
│   │   ├── AccessibilityToolbar.tsx # Font/contrast/voice controls
│   │   └── Header.tsx             # App header with session info
│   ├── hooks/            # Custom React hooks
│   │   ├── useVoiceRecording.ts   # MediaRecorder wrapper
│   │   ├── useSpeechToText.ts     # Calls backend /transcribe
│   │   ├── useTextToSpeech.ts     # Web Speech API wrapper
│   │   ├── useVisionModel.ts      # Calls NVIDIA NIM VLM
│   │   ├── useApiQuery.ts         # Calls backend /api/query
│   │   ├── useSession.ts          # Session management
│   │   └── useAccessibility.ts    # Accessibility preferences
│   ├── services/         # API services
│   │   └── api.ts                 # Axios client (only client; no mock exists)
│   ├── types/            # TypeScript interfaces
│   ├── utils/            # Utility functions
│   └── styles/           # CSS (CSS custom properties for theming)
├── public/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
└── .env
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `VITE_API_BASE_URL` | Backend API base URL | `http://localhost:8000` |
| `VITE_NIM_VLM_URL` | VLM proxy (backend, which adds the server key) | `http://localhost:8000/v1/chat/completions` |
| `VITE_NIM_VLM_MODEL` | VLM model name | `meta/llama-3.2-11b-vision-instruct` |

No `VITE_USE_MOCK` exists: the mock server and `mockApi.ts` were deleted, every request hits the real backend.

## API Contracts

### POST `/api/query` (Backend)
**Request:**
```json
{
  "session_id": "string",
  "input_text": "string",
  "input_source": "voice" | "text",
  "screen_context": "string"
}
```
**Response:**
```json
{
  "response_text": "string",
  "agent_used": "string",
  "suggested_action": "string",
  "confidence": "number"
}
```

### POST `/api/transcribe` (Backend)
**Request:** `multipart/form-data` with `audio` field (webm/opus)
**Response:**
```json
{ "transcript": "string" }
```

### POST `/v1/chat/completions` (NVIDIA NIM VLM)
**Request:**
```json
{
  "model": "meta/llama-3.2-11b-vision-instruct",
  "messages": [{
    "role": "user",
    "content": [
      { "type": "text", "text": "Describe this screenshot..." },
      { "type": "image_url", "image_url": { "url": "data:image/jpeg;base64,..." } }
    ]
  }],
  "max_tokens": 500
}
```

## Accessibility Features

- **WCAG 2.1 AA** compliant contrast ratios
- **Full keyboard navigation**: Tab, Enter, Escape, Space
- **Screen reader tested**: NVDA, JAWS compatible
- **ARIA live regions** for dynamic content
- **High contrast mode** (forced-colors media query support)
- **Reduced motion** support (prefers-reduced-motion)
- **Font scaling** via CSS custom properties
- **Voice speed/pitch/volume** controls

## Development

The frontend only talks to the real backend (`VITE_API_BASE_URL`, default
`http://localhost:8000`). Transcription is `POST /api/transcribe`
(faster-whisper server-side); vision goes through the backend VLM proxy
`POST /v1/chat/completions`, which attaches `NIM_API_KEY` server-side, so no
key ever ships in the JS bundle.

### NVIDIA NIM VLM Setup
```bash
# Local deployment (requires GPU)
docker run -d --gpus all -p 8000:8000 \
  -e NIM_SERVED_MODEL_NAME=meta/llama-3.2-11b-vision-instruct \
  nvcr.io/nim/meta/llama-3.2-11b-vision-instruct:latest
```
Then set `VITE_NIM_VLM_URL=http://localhost:8000/v1/chat/completions`

Or use NVIDIA hosted API (requires NGC API key):
- `VITE_NIM_VLM_URL=https://integrate.api.nvidia.com/v1/chat/completions`
- `VITE_NIM_API_KEY=your-ngc-key`

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start Vite dev server |
| `npm run build` | Production build |
| `npm run preview` | Preview production build |
| `npm run lint` | Run ESLint |

## Demo Checklist

- [ ] Page loads → welcome message spoken via TTS
- [ ] Hold mic → "Listening…" → speak → transcript appears
- [ ] Click send → "Thinking…" → response appears + spoken
- [ ] Upload screenshot → "Describing image…" → description shown
- [ ] Toggle high contrast → UI instantly adapts
- [ ] Adjust font size → all text scales
- [ ] Keyboard-only navigation works end-to-end
- [ ] Screen reader announces messages correctly

## License

MIT — College project for educational purposes.