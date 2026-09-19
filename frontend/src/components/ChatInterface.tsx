import { useState, useCallback, useEffect, useRef } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { MessageBubble } from './MessageBubble';
import { TextInput } from './TextInput';
import { MicButton } from './MicButton';
import { ScreenshotUpload } from './ScreenshotUpload';
import { StatusIndicator } from './StatusIndicator';
import { Header } from './Header';
import { HistoryPanel } from './HistoryPanel';
import { useAccessibility } from '../hooks/useAccessibility';
import { useSession } from '../hooks/useSession';
import { useVoiceRecording } from '../hooks/useVoiceRecording';
import { useSpeechToText } from '../hooks/useSpeechToText';
import { useTextToSpeech } from '../hooks/useTextToSpeech';
import { useVisionModel } from '../hooks/useVisionModel';
import { useApiQuery } from '../hooks/useApiQuery';
import { useBehaviorTracking } from '../hooks/useBehaviorTracking';
import { apiService } from '../services/api';
import type { Verbosity } from '../types/api';
import type { Message } from '../types/chat';
import type { DisabilityProfile, LanguageComplexity } from '../types/accessibility';

interface ChatInterfaceProps {
  initialScreenContext?: string;
}

// One starter per agent domain; clicking submits immediately so a screen-reader
// user gets an answer in one step instead of dictating into the composer.
const SUGGESTIONS = [
  { icon: '📝', text: 'How do I fill the permanent address field?' },
  { icon: '📄', text: 'Summarize this PDF for me' },
  { icon: '🧭', text: 'Where is the submit button on this page?' },
  { icon: '🎓', text: 'Explain photosynthesis in simple terms' },
];

export function ChatInterface({ initialScreenContext = '' }: ChatInterfaceProps) {
  // State
  const [inputValue, setInputValue] = useState('');
  const [screenContext, setScreenContext] = useState(initialScreenContext);
  const [status, setStatus] = useState<'idle' | 'listening' | 'thinking' | 'speaking'>('idle');
  const [showAccessibility, setShowAccessibility] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [verbosity, setVerbosity] = useState<Verbosity>('standard');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Hooks
  const {
    prefs,
    setFontSize,
    toggleContrast,
    setVoiceSpeed,
    setDisabilityProfile,
    setLanguageComplexity,
    resetToDefaults,
  } = useAccessibility();

  const {
    sessionId,
    history,
    addMessage,
    updateMessage,
    createNewSession,
    switchSession,
    sessions,
    loadSessions,
    sessionReady,
  } = useSession();

  // Answer-detail preference: local immediately, persisted to the backend when
  // it is reachable - the policy engine reads this row and rewrites answers,
  // so the toolbar choice genuinely changes future responses.
  useEffect(() => {
    if (!sessionReady) return;
    apiService.getPreferences()
      .then((p) => {
        setVerbosity(p.verbosity_level);
        setDisabilityProfile(p.disability_profile as DisabilityProfile);
        setLanguageComplexity(p.language_complexity as LanguageComplexity);
      })
      .catch(() => { /* demo mode: keep the local default */ });
  }, [sessionReady]);

  const handleVerbosityChange = useCallback((level: Verbosity) => {
    setVerbosity(level);
    apiService.updatePreferences({ 
      verbosity_level: level, 
      voice_speed: prefs.voiceSpeed,
      disability_profile: prefs.disabilityProfile,
      language_complexity: prefs.languageComplexity,
    })
      .catch(() => { /* demo mode: preference stays local-only */ });
  }, [prefs.voiceSpeed, prefs.disabilityProfile, prefs.languageComplexity]);

  const handleOpenHistory = useCallback(() => {
    loadSessions();
    setShowHistory(true);
  }, [loadSessions]);

  const {
    isRecording,
    recordingTime,
    startRecording,
    stopRecording,
    cancelRecording,
    error: recordingError,
  } = useVoiceRecording();

  const { transcribe, isTranscribing } = useSpeechToText();
  const { speak, stop: stopSpeaking, isSpeaking } = useTextToSpeech();
  const { describeImage, isDescribing } = useVisionModel();
  const { sendQuery, isQuerying } = useApiQuery();
  // Behavior signals: replay/skip feed policy Rule 5 (defaults only).
  // recordReplay fires from the per-answer Replay button; recordSkip from the
  // user-initiated stop-speaking control (an interruption, not a clean finish).
  const { recordReplay, recordSkip } = useBehaviorTracking(sessionId);

  // Sync status with recording/speaking state
  useEffect(() => {
    if (isRecording) {
      setStatus('listening');
    } else if (isSpeaking) {
      setStatus('speaking');
    } else if (isQuerying || isTranscribing || isDescribing) {
      setStatus('thinking');
    } else {
      setStatus('idle');
    }
  }, [isRecording, isSpeaking, isQuerying, isTranscribing, isDescribing]);

  // Scroll to bottom when messages change
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [history, scrollToBottom]);

  // Handle voice recording completion - real error TTS (accessibility critical)
  const handleRecordingComplete = useCallback(async () => {
    // stopRecording resolves once MediaRecorder has actually assembled the
    // blob; the old code read the (still null) state synchronously here, so
    // the first recording was always discarded before transcription.
    const blob = await stopRecording();
    if (!blob) return;

    try {
      const transcript = await transcribe(blob);
      setInputValue(transcript);
      // Auto-submit after transcription
      setTimeout(() => handleSubmit(transcript), 100);
    } catch (err) {
      console.error('Transcription failed:', err);
      const msg = 'Transcription failed. Please try again or type your message.';
      const errMsg: Message = { id: uuidv4(), role: 'assistant', content: msg, timestamp: new Date(), is_loading: false };
      addMessage(errMsg);
      await speak(msg);
    }
  }, [stopRecording, transcribe, addMessage, speak]);

  // Handle form submit
  const handleSubmit = useCallback(async (text?: string) => {
    const messageText = text || inputValue.trim();
    if (!messageText) return;
    // The session must exist server-side before the first query; bootstrap
    // creates it within a moment of load, so just wait it out.
    if (!sessionReady) return;

    // Add user message
    const userMessage: Message = {
      id: uuidv4(),
      role: 'user',
      content: messageText,
      timestamp: new Date(),
      input_source: text ? 'voice' : 'text',
      screen_context: screenContext || undefined,
    };
    addMessage(userMessage);
    setInputValue('');

    // Add placeholder assistant message
    const assistantId = uuidv4();
    const assistantMessage: Message = {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      is_loading: true,
    };
    addMessage(assistantMessage);

    setStatus('thinking');

    try {
      const response = await sendQuery({
        session_id: sessionId,
        input_text: messageText,
        input_source: text ? 'voice' : 'text',
        screen_context: screenContext || '',
      });

      // Update assistant message with response
      updateMessage(assistantId, {
        content: response.response_text,
        is_loading: false,
        agent_used: response.agent_used,
        suggested_action: response.suggested_action ?? undefined,
        confidence: response.confidence,
        sources: response.sources_used,
      });

      setStatus('speaking');
      await speak(response.response_text);
    } catch (err) {
      console.error('Query failed:', err);
      const errText = 'Sorry, I encountered an error. Please try again.';
      updateMessage(assistantId, {
        content: errText,
        is_loading: false,
      });
      await speak(errText);
    }
  }, [
    inputValue,
    screenContext,
    sessionId,
    sessionReady,
    addMessage,
    updateMessage,
    sendQuery,
    speak,
  ]);

  // Handle image upload - real error TTS
  const handleImageUpload = useCallback(async (file: File) => {
    try {
      const description = await describeImage(file);
      setScreenContext(description);
      const systemMessage: Message = {
        id: uuidv4(),
        role: 'system',
        content: `Image described: ${description}`,
        timestamp: new Date(),
      };
      addMessage(systemMessage);
      await speak(`Image analyzed: ${description.substring(0, 200)}`);
    } catch (err) {
      console.error('Image description failed:', err);
      const msg = 'Image description failed. Please try another screenshot.';
      addMessage({ id: uuidv4(), role: 'assistant', content: msg, timestamp: new Date() });
      await speak(msg);
    }
  }, [describeImage, addMessage, speak]);

  const handleRemoveImage = useCallback(() => {
    setScreenContext('');
  }, []);

  const handleNewSessionAndRefresh = useCallback(() => {
    createNewSession();
    setScreenContext('');
    setInputValue('');
    stopSpeaking();
    setShowHistory(false);
  }, [createNewSession, stopSpeaking]);

  // Replay path: the user didn't get the answer - re-speak it AND log the
  // signal so the policy engine can simplify subsequent answers.
  const handleReplayAnswer = useCallback((content: string) => {
    recordReplay();
    speak(content);
  }, [recordReplay, speak]);

  // Skip path: the user cut speech off - log it (too verbose) then stop.
  const handleStopSpeaking = useCallback(() => {
    recordSkip();
    stopSpeaking();
  }, [recordSkip, stopSpeaking]);

  const handleToggleAccessibility = useCallback(() => {
    setShowAccessibility((prev) => !prev);
  }, []);

  // Escape closes the accessibility panel and returns focus to its toggle,
  // matching the history panel's keyboard behaviour.
  useEffect(() => {
    if (!showAccessibility) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowAccessibility(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [showAccessibility]);

  // Download the whole conversation as a .txt transcript
  const handleDownloadTranscript = useCallback(() => {
    const lines = history.map((m) => {
      const who = m.role === 'user' ? 'You' : m.role === 'assistant' ? 'Assistant' : 'System';
      const time = m.timestamp.toLocaleString();
      return `[${time}] ${who}: ${m.content}`;
    });
    const blob = new Blob(
      [`AdaptiveAI conversation — ${new Date().toLocaleString()}\n\n${lines.join('\n\n')}\n`],
      { type: 'text/plain;charset=utf-8' },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `adaptiveai-transcript-${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }, [history]);

  // Welcome message, once per session. Gated on the session bootstrap finishing
  // (restoring history or creating the session server-side) so the greeting can
  // never race a history load and get wiped, and re-appears for a new session.
  // The ref also matters for React 18 StrictMode, which mounts every component
  // twice in dev - the Docker image runs the dev server - and would otherwise
  // greet users with two identical bubbles.
  const welcomedSession = useRef<string | null>(null);
  useEffect(() => {
    if (!sessionReady || welcomedSession.current === sessionId || history.length > 0) return;
    welcomedSession.current = sessionId;
    const welcomeMessage: Message = {
      id: uuidv4(),
      role: 'assistant',
      content: 'Welcome to AdaptiveAI! I can help you with forms, documents, web navigation, and learning. You can type, speak, or upload a screenshot to get started.',
      timestamp: new Date(),
      agent_used: 'general_agent',
    };
    addMessage(welcomeMessage);
    speak(welcomeMessage.content);
  }, [sessionReady, sessionId, history.length, addMessage, speak]);

  return (
    <div className="chat-interface" role="application">
      <Header
        sessionId={sessionId}
        onNewSession={handleNewSessionAndRefresh}
        onToggleHistory={handleOpenHistory}
        onDownloadTranscript={handleDownloadTranscript}
        canDownload={history.length > 1}
        fontSize={prefs.fontSize}
        contrastMode={prefs.contrastMode}
        voiceSpeed={prefs.voiceSpeed}
        verbosity={verbosity}
        disabilityProfile={prefs.disabilityProfile}
        languageComplexity={prefs.languageComplexity}
        onFontSizeChange={setFontSize}
        onContrastToggle={toggleContrast}
        onVoiceSpeedChange={setVoiceSpeed}
        onVerbosityChange={handleVerbosityChange}
        onDisabilityProfileChange={setDisabilityProfile}
        onLanguageComplexityChange={setLanguageComplexity}
        onResetAccessibility={resetToDefaults}
        showAccessibility={showAccessibility}
        onToggleAccessibility={handleToggleAccessibility}
      />

      <HistoryPanel
        open={showHistory}
        onClose={() => setShowHistory(false)}
        sessions={sessions}
        currentSessionId={sessionId}
        loading={false}
        onSelect={switchSession}
        onRefresh={loadSessions}
      />

      <main className="chat-main" role="main">
        <div 
          className="messages-container" 
          role="log" 
          aria-live="polite"
          aria-label="Conversation"
        >
          {history.map((message) => (
            <MessageBubble key={message.id} message={message} onReplay={handleReplayAnswer} />
          ))}

          {history.length === 1 && sessionReady && !isQuerying && (
            <div className="suggestion-chips" role="group" aria-label="Suggested questions">
              <span className="chips-label">Or start with one of these:</span>
              {SUGGESTIONS.map(({ icon, text }) => (
                <button
                  key={text}
                  type="button"
                  className="chip"
                  onClick={() => handleSubmit(text)}
                  disabled={isRecording}
                >
                  <span aria-hidden="true">{icon}</span> {text}
                </button>
              ))}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        <StatusIndicator status={status} listeningTime={recordingTime} onStopSpeaking={handleStopSpeaking} />
      </main>

      <footer className="chat-footer" role="contentinfo">
        <div className="input-row">
          <ScreenshotUpload
            onImageUpload={handleImageUpload}
            isDescribing={isDescribing}
            disabled={isQuerying || isRecording}
            currentImage={screenContext ? 'preview' : null}
            onRemoveImage={handleRemoveImage}
          />
          
          <div className="text-input-wrapper">
          <TextInput
            value={inputValue}
            onChange={setInputValue}
            onSubmit={handleSubmit}
            disabled={!sessionReady || isQuerying || isRecording}
            placeholder={
              !sessionReady ? 'Connecting…' : isRecording ? 'Recording…' : 'Type your message…'
            }
            ariaLabel="Message input"
          />
          </div>

          <MicButton
            onStartRecording={startRecording}
            onStopRecording={handleRecordingComplete}
            onCancelRecording={cancelRecording}
            isRecording={isRecording}
            recordingTime={recordingTime}
            disabled={isQuerying || isTranscribing || isDescribing || inputValue.trim().length > 0}
            error={recordingError}
          />
        </div>
      </footer>
    </div>
  );
}