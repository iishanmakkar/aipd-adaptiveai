import { useState, useCallback, useEffect, useRef } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { MessageBubble } from './MessageBubble';
import { TextInput } from './TextInput';
import { MicButton } from './MicButton';
import { ScreenshotUpload } from './ScreenshotUpload';
import { StatusIndicator } from './StatusIndicator';
import { Header } from './Header';
import { HistoryPanel } from './HistoryPanel';
import { FormFillDialog } from './FormFillDialog';
import type { FillableForm } from './FormFillDialog';
import { useAccessibility } from '../hooks/useAccessibility';
import { useSession } from '../hooks/useSession';
import { useVoiceRecording } from '../hooks/useVoiceRecording';
import { useSpeechToText } from '../hooks/useSpeechToText';
import { useTextToSpeech } from '../hooks/useTextToSpeech';
import { useVisionModel } from '../hooks/useVisionModel';
import { useApiQuery } from '../hooks/useApiQuery';
import { useBehaviorTracking } from '../hooks/useBehaviorTracking';
import { useScreenMonitor } from '../hooks/useScreenMonitor';
import { useInTabRAG } from '../hooks/useInTabRAG';
import { useVoiceCommands, VOICE_COMMANDS } from '../hooks/useVoiceCommands';
import { useDialogFocus } from '../hooks/useDialogFocus';
import { apiService } from '../services/api';
import { clearSessionId } from '../utils/session';
import { getEmail, signOut } from '../utils/auth';
import { isOfflineError } from '../utils/apiError';
import type { Verbosity, NarrationEvent, QueryRequest, QueryResponse } from '../types/api';
import type { Message } from '../types/chat';
import type { DisabilityProfile, LanguageComplexity } from '../types/accessibility';

interface ChatInterfaceProps {
  initialScreenContext?: string;
}

// One starter per agent domain; clicking submits immediately so a screen-reader
// user gets an answer in one step instead of dictating into the composer. The
// first chip is the whole blindfolded-booking journey: one press loads the demo
// page, speaks the note, and drops the cursor on the Fill this form button —
// no URL typing required.
const SUGGESTIONS = [
  { icon: '🎟️', text: 'Book my tickets on the demo booking page: http://demo-forms:8080/book-tickets.html' },
  { icon: '📝', text: 'How do I fill the permanent address field?' },
  { icon: '📄', text: 'Summarize this PDF for me' },
  { icon: '🧭', text: 'Where is the submit button on this page?' },
  { icon: '🎓', text: 'Explain photosynthesis in simple terms' },
];

export function ChatInterface({ initialScreenContext = '' }: ChatInterfaceProps) {
  // State
  const [inputValue, setInputValue] = useState('');
  const [screenContext, setScreenContext] = useState(initialScreenContext);
  // Phase 2.1: autonomous mode — goal → orchestrated plan → specialist.
  const [autonomous, setAutonomous] = useState(false);
  const [status, setStatus] = useState<'idle' | 'listening' | 'thinking' | 'speaking'>('idle');
  const [showAccessibility, setShowAccessibility] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [verbosity, setVerbosity] = useState<Verbosity>('standard');
  // Round 10: a live page with detected fields — the trigger for the real
  // form-fill pipeline (discover → cache → fill, with replay + heal).
  const [formPage, setFormPage] = useState<FillableForm | null>(null);
  const [fillDialogOpen, setFillDialogOpen] = useState(false);
  const fillFormButtonRef = useRef<HTMLButtonElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const paletteRef = useRef<HTMLDivElement>(null);
  // Busy while a page URL is loading in live Chromium (before isQuerying
  // flips): inputs stay disabled and the status reads "thinking" so a second
  // submit cannot start a concurrent turn and the user is not left in silence.
  const [loadingPage, setLoadingPage] = useState(false);

  // Hooks
  const {
    prefs,
    setFontSize,
    toggleContrast,
    setVoiceSpeed,
    setVoiceVolume,
    setUiScale,
    toggleBoldText,
    toggleWideSpacing,
    toggleDarkMode,
    toggleReadingFocus,
    setDisabilityProfile,
    setLanguageComplexity,
    resetToDefaults,
  } = useAccessibility();

  const {
    sessionId,
    history,
    isLoading,
    addMessage,
    updateMessage,
    createNewSession,
    switchSession,
    sessions,
    loadSessions,
    sessionReady,
    pollRemoteMessages,
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

  // Every toolbar knob persists to the backend (the policy engine reads the
  // stored row when shaping answers): previously only verbosity was sent and
  // a reload reverted everything else to server defaults. Partial PUT: only
  // the changed field travels, omitted fields are never wiped server-side.
  const persistPrefs = useCallback((overrides: {
    verbosity_level?: Verbosity; voice_speed?: number;
    disability_profile?: DisabilityProfile; language_complexity?: LanguageComplexity;
  }) => {
    if (Object.keys(overrides).length === 0) return;
    apiService.updatePreferences(overrides).catch(() => { /* demo mode: preference stays local-only */ });
  }, []);

  const handleVerbosityChange = useCallback((level: Verbosity) => {    setVerbosity(level);
    persistPrefs({ verbosity_level: level });
  }, [persistPrefs]);

  const handleVoiceSpeedChange = useCallback((speed: number) => {
    setVoiceSpeed(speed);
    persistPrefs({ voice_speed: speed });
  }, [persistPrefs, setVoiceSpeed]);

  const handleDisabilityProfileChange = useCallback((profile: DisabilityProfile) => {
    setDisabilityProfile(profile);
    persistPrefs({ disability_profile: profile });
  }, [persistPrefs, setDisabilityProfile]);

  const handleLanguageComplexityChange = useCallback((complexity: LanguageComplexity) => {
    setLanguageComplexity(complexity);
    persistPrefs({ language_complexity: complexity });
  }, [persistPrefs, setLanguageComplexity]);

  const handleAccessibilityReset = useCallback(() => {
    resetToDefaults();
    persistPrefs({
      verbosity_level: 'standard',
      voice_speed: 1.0,
      disability_profile: 'none',
      language_complexity: 'standard',
    });
  }, [persistPrefs, resetToDefaults]);

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
  } = useVoiceRecording({
    onAutoStop: (blob) => void handleRecordingCompleteRef.current?.(blob),
  });
  // The 30s auto-cap delivers its blob through the hook; the manual stop
  // delivers through MicButton. Both land in the same handler (set below).
  const handleRecordingCompleteRef = useRef<((blob?: Blob) => Promise<void>) | null>(null);

  const { transcribe, isTranscribing } = useSpeechToText();
  const { speak, stop: stopSpeaking, isSpeaking } = useTextToSpeech();
  const { describeImage, isDescribing } = useVisionModel();
  const { sendQuery, isQuerying } = useApiQuery();
  // Behavior signals: replay/skip feed policy Rule 5 (defaults only).
  // recordReplay fires from the per-answer Replay button; recordSkip from the
  // user-initiated stop-speaking control (an interruption, not a clean finish);
  // recordListen follows every fully-spoken chat answer with its duration.
  const { recordReplay, recordSkip, recordListen } = useBehaviorTracking(sessionId);

  // Round 9: continuous page monitoring. Consent is explicit (button / Alt+W /
  // "watch my screen" in chat); narrations arrive as special assistant
  // messages, announced by the polite live region below and spoken via TTS.
  const handleNarration = useCallback((narration: NarrationEvent) => {
    addMessage({
      id: `narration-${narration.id}`,
      role: 'assistant',
      // The prefix keeps a screen-update distinguishable from a chat answer
      // in the transcript and in the live-region announcement.
      content: `Screen update: ${narration.text}`,
      timestamp: new Date(narration.ts * 1000),
      agent_used: 'browser_agent',
      suggested_action: 'screen_narration',
    });
  }, [addMessage]);
  const { active: monitorActive, starting: monitorStarting, error: monitorError, toggle: toggleMonitor } =
    useScreenMonitor(sessionId, handleNarration);
  const { askFresh, stats: inTabStats } = useInTabRAG();

  // Phase 3.2: voice commands ("go back", "read that again", "bigger text",
  // "high contrast") + Cmd+K palette. Inlined new-session body to avoid
  // use-before-declare (handleNewSessionAndRefresh is defined below).
  const { paletteOpen, setPaletteOpen, handleTranscript } = useVoiceCommands({
    'go-back': () => { void speak('Going back is not available in the chat. Your conversation is safe.'); },
    replay: () => {
      const last = [...history].reverse().find((m) => m.role === 'assistant' && m.content);
      if (last) { stopSpeaking(); void speak(last.content); recordReplay(); }
      else void speak('Nothing to repeat yet.');
    },
    'bigger-text': () => { setFontSize('large'); void speak('Larger text on.'); recordReplay(); },
    'toggle-contrast': () => { toggleContrast(); void speak('Contrast changed.'); },
    'monitor-start': () => { if (!monitorActive) void toggleMonitor(); },
    'monitor-stop': () => { if (monitorActive) { void toggleMonitor(); void speak('Stopped watching.'); } },
    'fill-form': () => {
      if (formPage && !fillDialogOpen) {
        setFillDialogOpen(true);
        void speak(`Opening the form. ${formPage.fields.length} fields. Dictate each value, or say type followed by the words to enter them literally.`);
      } else if (!formPage) {
        void speak('No form is loaded. Paste a page link first, then say fill this form.');
      }
    },
    'submit-form': () => {
      if (formPage && fillDialogOpen) {
        window.dispatchEvent(new CustomEvent('adaptiveai:fill-submit'));
      } else void speak('No open form to submit.');
    },
    'close-form': () => {
      if (fillDialogOpen) {
        setFillDialogOpen(false);
        void speak('Form closed. Nothing was sent.');
      }
    },
    'new-session': () => {
      createNewSession();
      setScreenContext('');
      setInputValue('');
      stopSpeaking();
      setShowHistory(false);
      setFormPage(null);
      setFillDialogOpen(false);
      void speak('New session started.');
    },
  });
  useDialogFocus(paletteOpen, paletteRef);

  // Sync status with recording/speaking state
  useEffect(() => {
    if (isRecording) {
      setStatus('listening');
    } else if (isSpeaking) {
      setStatus('speaking');
    } else if (isQuerying || isTranscribing || isDescribing || loadingPage) {
      setStatus('thinking');
    } else {
      setStatus('idle');
    }
  }, [isRecording, isSpeaking, isQuerying, isTranscribing, isDescribing, loadingPage]);

  // Scroll to bottom when messages change
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [history, scrollToBottom]);

  // Handle form submit
  const submitInFlightRef = useRef(false);

  const runSubmit = useCallback(async (messageText: string, source: 'voice' | 'text') => {
    // User input outranks any narration in flight: cut speech immediately.
    // (The backend also opens a monitor quiet-window on every turn, so a
    // pending screen description is deferred, never spoken over the answer.)
    stopSpeaking();

    // Real page, not generic advice: if the message links a URL, load it in
    // the backend's live Chromium first and ask about what is ACTUALLY there.
    // Trailing sentence punctuation is stripped: it sailed into page-context
    // and failed the load ("Open http://example.com/x." 404'd).
    const rawUrl = messageText.match(/https?:\/\/[^\s)]+/i)?.[0];
    const pageUrl = rawUrl?.replace(/[.,;:!?'"\])]+$/, '');
    let effectiveScreenContext = screenContext || '';
    if (pageUrl) {
      setLoadingPage(true);
      void speak('Loading that page…');
      try {
        const page = await apiService.pageContext(pageUrl);
        const fieldLines = page.fields
          .map((f) => `- ${f.label} (${f.type}${f.required ? ', required' : ''})`)
          .join('\n');
        effectiveScreenContext =
          `Live page: ${page.title} (${page.url}). ${page.description}\n` +
          `Interactive fields:\n${fieldLines}`;
        const canFill = page.fields.length > 0;
        // A field-less (or failed) load must clear the previous form: keeping
        // it armed the footer button and dialog at the OLD url.
        setFormPage(canFill ? { url: page.url, fields: page.fields } : null);
        const note: Message = {
          id: uuidv4(), role: 'assistant',
          content: canFill
            ? `Loaded the live page: ${page.title} — ${page.field_count} interactive fields found. Press the Fill this form button to type a value for each field.`
            : `Loaded the live page: ${page.title}. Ask me about anything on it.`,
          timestamp: new Date(), is_loading: false,
        };
        addMessage(note);
        // Blindfolded-critical: without this the page-load note is only a
        // silent bubble — the user never learns the page loaded or that the
        // Fill this form button is now available.
        void speak(note.content);
        if (canFill) {
          // Move focus to the Fill button so keyboard/SR users land on it.
          setTimeout(() => fillFormButtonRef.current?.focus(), 50);
        }
      } catch {
        // One turn, one answer: a failed page load ends the turn here instead
        // of falling through to a generic backend answer as a second bubble.
        // It also clears any stale form from an earlier page.
        setFormPage(null);
        const fail: Message = {
          id: uuidv4(), role: 'assistant',
          content: 'I could not open that page (it may block automated browsing or need login). I can still help if you describe it or upload a screenshot.',
          timestamp: new Date(), is_loading: false,
        };
        addMessage(fail);
        await speak(fail.content);
        return;
      } finally {
        setLoadingPage(false);
      }
    }

    // Add user message
    const userMessage: Message = {
      id: uuidv4(),
      role: 'user',
      content: messageText,
      timestamp: new Date(),
      input_source: source,
      screen_context: effectiveScreenContext || undefined,
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

    // One request shape for both paths: sent now when online, queued whole
    // when the network is down (the drain replays it verbatim).
    const request: QueryRequest = {
      session_id: sessionId,
      input_text: messageText,
      input_source: source,
      screen_context: effectiveScreenContext,
      autonomous,
      // Phase 2.2: the fused context the backend folds into screen_ctx.
      // Behavior travels separately via POST /api/behavior-event.
      unified_context: {
        screen_text: effectiveScreenContext,
        dom_snapshot: '',
        disability_profile: prefs.disabilityProfile,
      },
    };

    try {
      const response = await sendQuery(request);

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
      const listenStart = Date.now();
      await speak(response.response_text);
      // Fully heard answers are listen signals (duration in seconds); an
      // interrupted answer records skip instead via handleStopSpeaking.
      recordListen(Math.max(0, (Date.now() - listenStart) / 1000));
    } catch (err) {
      // Offline: the network never answered. Queue the whole query for the
      // online-drain in main.tsx instead of losing the user's question —
      // a server-side 4xx/5xx is NOT offline and still takes the error path.
      if (isOfflineError(err)) {
        try {
          const { enqueueMutation } = await import('../utils/offlineQueue');
          await enqueueMutation({ url: '/api/query', method: 'POST', body: request });
          const queuedText = 'You seem to be offline. Your question is saved and will be sent automatically when the connection returns.';
          updateMessage(assistantId, { content: queuedText, is_loading: false });
          await speak(queuedText);
          return;
        } catch {
          // IndexedDB unavailable: fall through to the normal error message.
        }
      }
      console.error('Query failed:', err);
      const errText = 'Sorry, I encountered an error. Please try again.';
      updateMessage(assistantId, {
        content: errText,
        is_loading: false,
      });
      await speak(errText);
    }
  }, [
    screenContext,
    autonomous,
    prefs.disabilityProfile,
    sessionId,
    addMessage,
    updateMessage,
    sendQuery,
    speak,
    stopSpeaking,
  ]);

  // Public submit with a re-entrancy guard around runSubmit: a URL message
  // awaits page-context BEFORE isQuerying flips, and a second submit in that
  // window used to start a concurrent turn (duplicated page loads,
  // interleaved speech). `source` is explicit — chips and typed text are
  // 'text'; only the transcription pipeline passes 'voice' (chip clicks used
  // to be recorded as voice input).
  const handleSubmit = useCallback(async (text?: string, source: 'voice' | 'text' = 'text') => {
    const messageText = text || inputValue.trim();
    if (!messageText) return;
    // The session must exist server-side before the first query; bootstrap
    // creates it within a moment of load, so just wait it out.
    if (!sessionReady) return;
    // A second submit mid-turn used to vanish silently (page loads take
    // 30-60s before isQuerying flips). Say so instead of looking broken.
    if (submitInFlightRef.current) {
      if (loadingPage || isQuerying) void speak('Still working on your last message.');
      return;
    }
    submitInFlightRef.current = true;
    try {
      await runSubmit(messageText, source);
    } finally {
      submitInFlightRef.current = false;
    }
  }, [inputValue, sessionReady, runSubmit, loadingPage, isQuerying, speak]);

  /** Jump to a previous session; the bootstrap effect loads its history.
   * Screenshot context, the armed fill form/dialog, and the draft input
   * belong to the old session: all of them once leaked across the switch
   * and queried/filled the wrong page, so they are cleared here. (History
   * itself is cleared inside switchSession for the same reason.) */
  const handleSelectSession = useCallback((id: string) => {
    switchSession(id);
    setScreenContext('');
    setFormPage(null);
    setFillDialogOpen(false);
    setInputValue('');
    stopSpeaking();
  }, [switchSession, stopSpeaking]);
  // Phase 1.3: in-tab RAG — index page DOM + history locally, answer from it
  // when possible, otherwise the normal backend path runs unchanged.
  // askFresh builds + searches in one synchronous pass, so even the first
  // click queries the just-built index (no stale-state fallthrough).
  const handleAskThisPage = useCallback(() => {
    const q = inputValue.trim() || 'Summarize this page';
    const freshHits = askFresh(history, q);
    if (freshHits) {
      addMessage({
        id: uuidv4(), role: 'assistant',
        content: `From this page:\n\n${freshHits.map((h) => `• (${h.source}) ${h.text.slice(0, 400)}`).join('\n\n')}`,
        timestamp: new Date(), agent_used: 'intab_rag',
      });
    } else {
      void handleSubmit(q);
    }
  }, [askFresh, history, inputValue, addMessage, handleSubmit]);

  // Handle voice recording completion - real error TTS (accessibility critical)
  const handleRecordingComplete = useCallback(async (blobOverride?: Blob) => {
    // The user started talking: any narration stops immediately.
    stopSpeaking();
    // stopRecording resolves once MediaRecorder has actually assembled the
    // blob; the old code read the (still null) state synchronously here, so
    // the first recording was always discarded before transcription. The
    // 30s auto-cap passes its already-captured blob through blobOverride.
    const blob = blobOverride ?? await stopRecording();
    if (!blob) return;

    try {
      const transcript = await transcribe(blob);
      // "type X" is the literal escape: a form value that happens to match a
      // command ("high contrast", "go back", "new session") must be typable.
      const typed = transcript.match(/^\s*type\s+(.+)$/i)?.[1]?.trim();
      const effective = typed ?? transcript;
      if (!typed && handleTranscript(transcript)) return;
      if (fillDialogOpen) {
        // The dialog is the active fill surface: dictate into it, not chat.
        // Chat slot-fill keeps working when the dialog is closed.
        window.dispatchEvent(new CustomEvent('adaptiveai:dialog-dictation', {
          detail: { text: effective },
        }));
        return;
      }
      setInputValue(effective);
      // Auto-submit after transcription
      setTimeout(() => handleSubmit(effective, 'voice'), 100);
    } catch (err) {
      console.error('Transcription failed:', err);
      const msg = 'Transcription failed. Please try again or type your message.';
      const errMsg: Message = { id: uuidv4(), role: 'assistant', content: msg, timestamp: new Date(), is_loading: false };
      addMessage(errMsg);
      await speak(msg);
    }
  }, [stopRecording, transcribe, addMessage, speak, stopSpeaking, handleSubmit, handleTranscript, fillDialogOpen]);

  // Wire the 30s auto-cap path: the hook above reads this ref at fire time.
  useEffect(() => {
    handleRecordingCompleteRef.current = handleRecordingComplete;
  }, [handleRecordingComplete]);

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
    setFormPage(null);
    setFillDialogOpen(false);
  }, [createNewSession, stopSpeaking]);

  // Phase 3.2: voice commands + Cmd+K palette (placed after all handlers).
  // (migrated earlier to avoid use-before-declare; see block above)
  // Replay path: the user didn't get the answer - re-speak it AND log the
  // signal so the policy engine can simplify subsequent answers. Double taps
  // within 1.5s count once: one gesture must not cross the >=2 threshold.
  const lastReplayAt = useRef(0);
  const handleReplayAnswer = useCallback((content: string) => {
    const now = Date.now();
    if (now - lastReplayAt.current > 1500) recordReplay();
    lastReplayAt.current = now;
    stopSpeaking();
    void speak(content);
  }, [recordReplay, speak, stopSpeaking]);

  // Skip path: the user cut speech off - log it (too verbose) then stop.
  const handleStopSpeaking = useCallback(() => {
    if (isSpeaking) recordSkip();
    stopSpeaking();
  }, [recordSkip, stopSpeaking, isSpeaking]);

  // Screen-reader-only users mute the app voice; text announcements stay in
  // the live regions. Volume 0 is the persisted mute flag (no schema change).
  const handleMuteToggle = useCallback(() => {
    const muted = prefs.voiceVolume !== 0;
    setVoiceVolume(muted ? 0 : 1);
    if (muted) stopSpeaking();
    else void speak('App voice on.');
  }, [prefs.voiceVolume, setVoiceVolume, stopSpeaking, speak]);

  const handleToggleAccessibility = useCallback(() => {
    setShowAccessibility((prev) => !prev);
  }, []);

  // Phase 4.2: hand a caregiver or support worker a read-only link to THIS
  // session. The backend mints a random 24h token; anything the helper types
  // arrives back as a note the user hears, so help can arrive without anyone
  // touching this person's keyboard.
  const [shareBusy, setShareBusy] = useState(false);
  const [accountMessage, setAccountMessage] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);

  const handleShare = useCallback(async () => {
    if (shareBusy) return;
    setShareBusy(true);
    setAccountMessage('');
    try {
      const share = await apiService.createShare(sessionId);
      const url = `${window.location.origin}/shared/${share.share_token}`;
      setAccountMessage(`Share link ready, valid 24 hours: ${url}`);
      // The link must live in the transcript, not only in the (closed)
      // account popover: the conversation log is what a screen reader
      // announces and what the user can re-read or copy later.
      addMessage({
        id: uuidv4(), role: 'assistant',
        // No punctuation touches the URL: clients extract links from prose
        // and a glued-on period breaks the /shared/<token> route.
        content: `Share link ready, valid 24 hours — ${url} — give it to the person helping you. Anything they type arrives here as a note you will hear.`,
        timestamp: new Date(), is_loading: false,
        agent_used: 'share',
      });
      speak(`Share link created. Give this address to the person helping you: ${url}`);
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      const reason = status === 404
        ? 'This conversation is not saved on the server yet, so there is nothing to share. Ask a question first.'
        : 'The share link could not be created right now. Please try again.';
      setAccountMessage(reason);
      addMessage({
        id: uuidv4(), role: 'assistant',
        content: reason, timestamp: new Date(), is_loading: false,
      });
      void speak(reason);
    } finally {
      setShareBusy(false);
    }
  }, [sessionId, shareBusy, speak, addMessage]);

  const handleSignOut = useCallback(() => {
    stopSpeaking();
    // The chat session pointer belongs to this account's browser; a different
    // user signing in must not inherit the transcript on screen.
    clearSessionId();
    signOut();
  }, [stopSpeaking]);

  const handleDeleteAccount = useCallback(async () => {
    setConfirmDelete(false);
    setAccountMessage('Deleting your account and every message in it…');
    stopSpeaking();
    try {
      await apiService.deleteAccount();
      clearSessionId();
      signOut();  // 204 means the rows are gone; nothing to stay signed into
    } catch {
      const msg = 'Your account could not be deleted right now. Nothing was removed - please try again.';
      setAccountMessage(msg);
      void speak(msg);
    }
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

  // Queued answers coming home: when the offline drain in main.tsx replays a
  // /api/query that was saved while offline, the response lands here so the
  // answer appears (and is spoken) in the same conversation the user asked it
  // in. Answers for other sessions are already persisted server-side; their
  // history shows them on switch.
  useEffect(() => {
    const onQueuedAnswer = (event: Event) => {
      const detail = (event as CustomEvent<{ request?: QueryRequest; response?: QueryResponse }>).detail;
      if (!detail?.response?.response_text) return;
      if (detail.request?.session_id !== sessionId) return;
      addMessage({
        id: uuidv4(),
        role: 'assistant',
        content: detail.response.response_text,
        timestamp: new Date(),
        agent_used: detail.response.agent_used,
        suggested_action: detail.response.suggested_action ?? undefined,
        confidence: detail.response.confidence,
        sources: detail.response.sources_used,
      });
      void speak(detail.response.response_text);
    };
    window.addEventListener('adaptiveai:queued-answer', onQueuedAnswer);
    return () => window.removeEventListener('adaptiveai:queued-answer', onQueuedAnswer);
  }, [sessionId, addMessage, speak]);

  // Interrupted-recording recovery: useVoiceRecording parks the audio of a
  // recording that died with an unmount or page unload. Once the session is
  // ready, take (read+delete, atomic) any draft and run the normal
  // transcribe → submit pipeline, so the user's words are never just gone.
  const recoveredDraftRef = useRef(false);
  useEffect(() => {
    if (!sessionReady || recoveredDraftRef.current) return;
    recoveredDraftRef.current = true;
    void (async () => {
      const { takeAudioDraft } = await import('../utils/offlineQueue');
      const draft = await takeAudioDraft().catch(() => null);
      if (!draft) return;
      addMessage({
        id: uuidv4(), role: 'assistant',
        content: 'Recovered the recording that was interrupted last time. Sending it for transcription…',
        timestamp: new Date(), is_loading: false,
      });
      try {
        const transcript = await transcribe(draft);
        if (handleTranscript(transcript)) return;
        setInputValue(transcript);
        setTimeout(() => void handleSubmit(transcript, 'voice'), 100);
      } catch {
        const msg = 'The recovered recording could not be transcribed. You can record it again.';
        addMessage({ id: uuidv4(), role: 'assistant', content: msg, timestamp: new Date(), is_loading: false });
        await speak(msg);
      }
    })();
  }, [sessionReady, addMessage, transcribe, handleTranscript, handleSubmit, speak]);

  // Caregiver loop, user side: a helper note is written to the session from
  // ANOTHER browser, so nothing pushes it here — poll quietly while the tab
  // is visible and the app is idle, and speak any note that arrives.
  useEffect(() => {
    if (!sessionReady) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      if (isQuerying || isTranscribing || isDescribing) return;
      if (history.some((m) => m.is_loading)) return;
      void pollRemoteMessages().then((added) => {
        added.filter((m) => m.role === 'assistant' && /^Helper note:/i.test(m.content))
          .forEach((m) => void speak(m.content));
      });
    }, 15000);
    return () => window.clearInterval(timer);
  }, [sessionReady, isQuerying, isTranscribing, isDescribing, history, pollRemoteMessages, speak]);

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
    <div className="chat-interface">
      <Header
        sessionId={sessionId}
        email={getEmail()}
        onNewSession={handleNewSessionAndRefresh}
        onShare={handleShare}
        shareBusy={shareBusy}
        accountMessage={accountMessage}
        onSignOut={handleSignOut}
        onDeleteAccount={handleDeleteAccount}
        confirmDeleteAccount={confirmDelete}
        onRequestDeleteAccount={() => setConfirmDelete(true)}
        onCancelDeleteAccount={() => setConfirmDelete(false)}
        onToggleHistory={handleOpenHistory}
        onDownloadTranscript={handleDownloadTranscript}
        canDownload={history.length > 1}
        fontSize={prefs.fontSize}
        contrastMode={prefs.contrastMode}
        voiceSpeed={prefs.voiceSpeed}
        muted={prefs.voiceVolume === 0}
        uiScale={prefs.uiScale}
        boldText={prefs.boldText}
        wideSpacing={prefs.wideSpacing}
        darkMode={prefs.theme === 'dark'}
        readingFocus={prefs.readingFocus}
        verbosity={verbosity}
        disabilityProfile={prefs.disabilityProfile}
        languageComplexity={prefs.languageComplexity}
        onFontSizeChange={setFontSize}
        onContrastToggle={toggleContrast}
            onVoiceSpeedChange={handleVoiceSpeedChange}
        onMuteToggle={handleMuteToggle}
        onUiScaleChange={setUiScale}
        onBoldToggle={toggleBoldText}
        onSpacingToggle={toggleWideSpacing}
        onDarkToggle={toggleDarkMode}
        onReadingToggle={toggleReadingFocus}
        onVerbosityChange={handleVerbosityChange}
            onDisabilityProfileChange={handleDisabilityProfileChange}
            onLanguageComplexityChange={handleLanguageComplexityChange}
            onResetAccessibility={handleAccessibilityReset}
        showAccessibility={showAccessibility}
        onToggleAccessibility={handleToggleAccessibility}
      />

      <HistoryPanel
        open={showHistory}
        onClose={() => setShowHistory(false)}
        sessions={sessions}
        currentSessionId={sessionId}
        loading={isLoading}
        onSelect={handleSelectSession}
        onRefresh={loadSessions}
      />

      {paletteOpen && (
        <div ref={paletteRef} role="dialog" aria-modal="true" aria-label="Voice command palette" className="command-palette">
          <h2>Voice commands</h2>
          <p>Say or pick one. Say “type” before words to enter them literally as a form value.</p>
          <ul>
            {VOICE_COMMANDS.map((cmd) => (
              <li key={cmd.action}>
                <button type="button" onClick={() => { handleTranscript(cmd.label.toLowerCase()); setPaletteOpen(false); }}>
                  {cmd.label}
                </button>
              </li>
            ))}
          </ul>
          <button type="button" onClick={() => setPaletteOpen(false)}>Close (Esc)</button>
        </div>
      )}

      {formPage && fillDialogOpen && (
        <FormFillDialog
          page={formPage}
          onClose={() => setFillDialogOpen(false)}
          announce={speak}
        />
      )}

      {/* id + tabIndex: the skip link's destination. Focus has to actually move
          here, or a keyboard user still tabs through the whole header. */}
      <main className="chat-main" id="main-content" tabIndex={-1} role="main">
        {/* The ONE live region for the conversation. Bubbles must not declare
            their own aria-live: nested polite regions make a screen reader
            announce the same answer two or three times. */}
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
                  disabled={isRecording || isQuerying || loadingPage}
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
        {/* Round 9: explicit monitor consent + persistent indicator + one-action
            stop. aria-pressed exposes the state to screen readers; the pulsing
            dot is the visual indicator for sighted observers; Alt+W is the
            keyboard kill switch registered in useScreenMonitor. */}
        <div className="monitor-bar" role="group" aria-label="Page actions">
          {formPage && (
            <button
              type="button"
              ref={fillFormButtonRef}
              className="monitor-toggle"
              aria-haspopup="dialog"
              aria-expanded={fillDialogOpen}
              onClick={() => setFillDialogOpen(true)}
            >
              Fill this form ({formPage.fields.length} fields)
            </button>
          )}
          <button
            type="button"
            className="monitor-toggle"
            aria-haspopup="dialog"
            aria-keyshortcuts="meta+k control+k"
            title="Open voice command palette (Cmd+K / Ctrl+K)"
            onClick={() => setPaletteOpen(true)}
          >
            Voice commands
          </button>
          <button
            type="button"
            className="monitor-toggle"
            onClick={handleAskThisPage}
            disabled={!sessionReady || isQuerying || loadingPage}
            title={inTabStats.chunks > 0 ? `Local index: ${inTabStats.chunks} chunks` : 'Index this page locally and answer offline-first'}
          >
            Ask this page
          </button>
          <label className="autonomous-toggle" title="Route via the orchestrator: goal → plan → specialist agent. Applies to the next message; text specialists only, not live-browser turns.">
            <input
              type="checkbox"
              checked={autonomous}
              disabled={isQuerying || loadingPage}
              onChange={(e) => setAutonomous(e.target.checked)}
              aria-label="Autonomous mode: plan and route via orchestrator"
            />
            Autonomous
          </label>
          <button
            type="button"
            className={`monitor-toggle${monitorActive ? ' active' : ''}`}
            aria-pressed={monitorActive}
            onClick={() => void toggleMonitor()}
            disabled={!sessionReady || monitorStarting}
          >
            <span
              className={`monitor-dot${monitorActive ? ' pulsing' : ''}`}
              aria-hidden="true"
            />
            {monitorActive
              ? 'Stop watching screen (Alt+W)'
              : monitorStarting
                ? 'Starting…'
                : 'Watch my screen (Alt+W)'}
          </button>
          <span className="visually-hidden" role="status" aria-live="polite">
            {monitorActive
              ? 'Screen monitoring is on. Every meaningful change on the live page will be narrated. Press Alt+W or use this button to stop.'
              : 'Screen monitoring is off.'}
          </span>
          {monitorError && !monitorActive && (
            <span className="monitor-error" role="alert">{monitorError}</span>
          )}
          {monitorActive && (
            <span className="monitor-hint" aria-hidden="true">
              narrating meaningful changes · stop: button, Alt+W, or say “stop watching my screen”
            </span>
          )}
        </div>
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
            disabled={!sessionReady || isQuerying || isRecording || loadingPage}
            placeholder={
              !sessionReady ? 'Connecting…' : isRecording ? 'Recording…' : loadingPage ? 'Loading page…' : 'Type your message…'
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