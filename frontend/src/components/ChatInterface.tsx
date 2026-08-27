import { useState, useCallback, useEffect, useRef } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { MessageBubble } from './MessageBubble';
import { TextInput } from './TextInput';
import { MicButton } from './MicButton';
import { ScreenshotUpload } from './ScreenshotUpload';
import { StatusIndicator } from './StatusIndicator';
import { Header } from './Header';
import { useAccessibility } from '../hooks/useAccessibility';
import { useSession } from '../hooks/useSession';
import { useVoiceRecording } from '../hooks/useVoiceRecording';
import { useSpeechToText } from '../hooks/useSpeechToText';
import { useTextToSpeech } from '../hooks/useTextToSpeech';
import { useVisionModel } from '../hooks/useVisionModel';
import { useApiQuery } from '../hooks/useApiQuery';
import type { Message } from '../types/chat';

interface ChatInterfaceProps {
  initialScreenContext?: string;
}

export function ChatInterface({ initialScreenContext = '' }: ChatInterfaceProps) {
  // State
  const [inputValue, setInputValue] = useState('');
  const [screenContext, setScreenContext] = useState(initialScreenContext);
  const [status, setStatus] = useState<'idle' | 'listening' | 'thinking' | 'speaking'>('idle');
  const [showAccessibility, setShowAccessibility] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Hooks
  const {
    prefs,
    setFontSize,
    toggleContrast,
    setVoiceSpeed,
    resetToDefaults,
  } = useAccessibility();

  const {
    sessionId,
    history,
    addMessage,
    updateMessage,
    createNewSession,
  } = useSession();

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
    const blob = stopRecording();
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
        suggested_action: response.suggested_action,
        confidence: response.confidence,
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

  const handleNewSession = useCallback(() => {
    createNewSession();
    setScreenContext('');
    setInputValue('');
    stopSpeaking();
  }, [createNewSession, stopSpeaking]);

  const handleToggleAccessibility = useCallback(() => {
    setShowAccessibility((prev) => !prev);
  }, []);

  // Welcome message on first load
  useEffect(() => {
    if (history.length === 0) {
      const welcomeMessage: Message = {
        id: uuidv4(),
        role: 'assistant',
        content: 'Welcome to AdaptiveAI! I can help you with forms, documents, web navigation, and learning. You can type, speak, or upload a screenshot to get started.',
        timestamp: new Date(),
        agent_used: 'general_agent',
      };
      addMessage(welcomeMessage);
      speak(welcomeMessage.content);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="chat-interface" role="application">
      <Header
        sessionId={sessionId}
        onNewSession={handleNewSession}
        fontSize={prefs.fontSize}
        contrastMode={prefs.contrastMode}
        voiceSpeed={prefs.voiceSpeed}
        onFontSizeChange={setFontSize}
        onContrastToggle={toggleContrast}
        onVoiceSpeedChange={setVoiceSpeed}
        onResetAccessibility={resetToDefaults}
        showAccessibility={showAccessibility}
        onToggleAccessibility={handleToggleAccessibility}
      />

      <main className="chat-main" role="main">
        <div 
          className="messages-container" 
          role="log" 
          aria-live="polite"
          aria-label="Conversation"
        >
          {history.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          <div ref={messagesEndRef} />
        </div>

        <StatusIndicator status={status} listeningTime={recordingTime} />
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
              disabled={isQuerying || isRecording}
              placeholder={isRecording ? 'Recording…' : 'Type your message…'}
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