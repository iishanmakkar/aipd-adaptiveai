import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  AppState,
  Animated,
  Easing,
  FlatList,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import {
  assist,
  assistAvailable,
  ensureMicPermission,
  ensureNotificationPermission,
  setVoiceHold,
  startAssistLoop,
  subscribeVoice,
} from '../../src/native/assist';
import type { AssistStatus } from '../../src/native/assist';
import { listenOnce, runAgent } from '../../src/services/agent';
import type { AgentEvent } from '../../src/services/agent';
import { composeSosMessage, describeSos, sendSos } from '../../src/services/careCircle';
import { runOrchestrated } from '../../src/services/orchestrator';
import type { OrchestratorEvent } from '../../src/services/orchestrator';
import { describeScreen } from '../../src/services/screenDescribe';
import {
  recordFrequentTask,
  recordTask,
  useGeminiApiKey,
  useGeminiKeyUncertain,
  useProfile,
  useSettings,
} from '../../src/services/profile';
import type { TaskRecord } from '../../src/services/profile';
import { useTheme } from '../../src/ui/AppProviders';
import { alertFeedback, Button, Card, Chip, Pill, ProgressBar } from '../../src/ui/components';
import { elevation, scaled, SPACE } from '../../src/theme';

type LogLine = {
  id: string;
  kind: 'plan' | 'status' | 'action' | 'observation' | 'message' | 'error';
  text: string;
  ok?: boolean;
};

let logSeq = 0;
const nextId = () => `l${Date.now()}-${logSeq++}`;

/** Deterministic voice shortcuts, checked before anything is sent to a model. */
// SOS requires an imperative verb (or the standalone phrases) so questions like
// "what should I do in an emergency" do not fire the emergency flow.
const SOS_PATTERN =
  /\b(send|start|call|trigger|issue)\s+(an?\s+)?(sos|emergency)\b|\bsend help\b|\bi need help\b|\bcall (for )?help\b|\bplease help\b/i;
// The note shortcut runs BEFORE the SOS pattern so "record an emergency note" records a note.
const NOTE_PATTERN = /\b(record|take|save|note)\s+(an?\s+)?(emergency\s+)?(voice\s+)?(note|this|message)\b/i;
// Danger words — ANY-length utterance containing these triggers SOS immediately.
// Broad by design: in danger, a false alarm is better than a missed emergency.
// Real cries are long ("I fell and I am hurt badly", "my house is on fire") — no word cap.
// Questions ("what should I do in an emergency?") and screen-asks ("help me read the screen")
// are excluded; explicit SOS verbs always win.
const DANGER_PATTERN =
  /\b(help|emergency|danger|sos|accident|fire|police|ambulance|hospital|medical|injured|hurt|attacked|stolen|trapped|stuck|fell|fallen|unconscious)\b/i;
const QUESTION_PREFIX = /^\s*(what|how|should|can you tell|tell me|is there)\b/i;
function isDangerUtterance(text: string): boolean {
  if (!text) return false;
  if (NOTE_PATTERN.test(text)) return false;
  if (SCREEN_ASK_PATTERN.test(text) && !SOS_PATTERN.test(text)) return false;
  if (SOS_PATTERN.test(text)) return true;
  if (QUESTION_PREFIX.test(text.trim())) return false;
  return DANGER_PATTERN.test(text);
}
const SCREEN_ASK_PATTERN =
  /what('s| is) on (my|the) screen|describe.*screen|where am i|what do you see|read (my|the) screen|describe (my|the) screen|can you see (my|the) screen|what('s| is) in front of me/i;

export default function AssistantScreen() {
  const theme = useTheme();
  const router = useRouter();
  const params = useLocalSearchParams<{ task?: string; nonce?: string }>();
  const settings = useSettings();
  const profile = useProfile();
  const geminiApiKey = useGeminiApiKey();
  const keyUncertain = useGeminiKeyUncertain();

  const [status, setStatus] = useState<AssistStatus | null>(null);
  const [log, setLog] = useState<LogLine[]>([]);
  const [draft, setDraft] = useState('');
  const [partial, setPartial] = useState('');
  const [listening, setListening] = useState(false);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<{ step: number; max: number } | null>(null);
  const [planLine, setPlanLine] = useState('');
  const [pendingConfirm, setPendingConfirm] = useState<{ label: string; resolve: (y: boolean) => void; kind?: 'sos' | 'agent' } | null>(null);
  const pendingConfirmRef = useRef<{ label: string; resolve: (y: boolean) => void; kind?: 'sos' | 'agent' } | null>(null);
  const setPending = (v: { label: string; resolve: (y: boolean) => void; kind?: 'sos' | 'agent' } | null) => {
    pendingConfirmRef.current = v;
    setPendingConfirm(v);
  };
  const sosBusyRef = useRef(false);
  // SINGLE way to dismiss the confirm dialog. Every path that hides it must settle its
  // promise first: an orphaned resolver leaves runSos()'s `await` hanging forever, so
  // sosBusyRef never resets and the emergency button degrades into a permanent
  // "Emergency dialog already open." no-op until the process restarts.
  const clearPending = (result: boolean) => {
    const p = pendingConfirmRef.current;
    pendingConfirmRef.current = null;
    setPendingConfirm(null);
    if (!p) return;
    // Belt and braces: if this was the SOS dialog, release the SOS latch even if the
    // awaiting runSos() somehow never resumes.
    if (p.kind === 'sos') sosBusyRef.current = false;
    p.resolve(result);
  };
  const statusSeqRef = useRef(0);
  // Bumped when the app returns to the foreground with a dead session, to re-run the
  // background-listening effect (the FGS cannot be re-promoted from the background itself).
  const [sessionNonce, setSessionNonce] = useState(0);

  const abortRef = useRef<AbortController | null>(null);
  const runTokenRef = useRef(0);
  const cancelledVoiceRef = useRef(false);
  const listRef = useRef<FlatList<LogLine>>(null);
  const lastInstructionRef = useRef('');
  const announcedOffRef = useRef(false);
  const sessionLoopRef = useRef<{ stop: () => void; active: () => boolean } | null>(null);
  const runningRef = useRef(false);
  // The background loop's handlers live for the whole session, but `run` is recreated whenever
  // the Gemini key or accessibility state changes. The loop callback must always call the latest.
  const runRef = useRef<(instruction: string) => Promise<void>>(async () => {});
  const u = profile.uiScale;

  const push = useCallback((line: Omit<LogLine, 'id'>) => {
    setLog((prev) => [...prev.slice(-120), { ...line, id: nextId() }]);
  }, []);

  const speak = useCallback(
    (text: string) => {
      if (!settings.speakResponses || !text || !assistAvailable) return;
      void assist.speak(text, settings.speechRate, settings.language).catch(() => {});
    },
    [settings.speakResponses, settings.speechRate, settings.language],
  );

  const refreshStatus = useCallback(async () => {
    if (!assistAvailable) return;
    const seq = ++statusSeqRef.current;
    try {
      const st = await assist.getStatus();
      if (seq === statusSeqRef.current) setStatus(st);
    } catch {
      if (seq === statusSeqRef.current) setStatus(null);
    }
  }, []);

  // Speak readiness only AFTER the bridge is up and status is loaded — speaking at
  // 1200ms used to trigger TextToSpeech init while Hermes/SoLoader were still loading
  // on slow devices, which trips the ANR "isn't responding" dialog on launch.
  const greetedRef = useRef(false);
  useEffect(() => {
    if (greetedRef.current || status == null) return;
    greetedRef.current = true;
    const t = setTimeout(() => {
      speak('AdaptiveAI ready. Tap the mic, or type a task. Say “What is on my screen?” any time. If you are in danger, say “help” and I will alert your emergency contacts.');
    }, 2500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  useEffect(() => {
    refreshStatus();
    // Polling here kept the window permanently dirty, which starved first draws and made
    // uiautomator dumps unreliable. Refresh when the app returns to the foreground instead.
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'active') void refreshStatus();
    });
    return () => sub.remove();
  }, [refreshStatus]);

  // The accessibility pill is the user's only signal about whether the app can see the screen at
  // all, so re-check it whenever this screen comes back into focus (e.g. after granting the
  // permission in system settings and returning).
  useFocusEffect(
    useCallback(() => {
      void refreshStatus();
    }, [refreshStatus]),
  );

  // A blind user cannot see the accessibility pill, and a silent failure here means the whole app
  // does nothing. Say it out loud, once per transition.
  useEffect(() => {
    if (!status) return;
    if (status.accessibilityEnabled) {
      if (announcedOffRef.current) {
        speak('Accessibility is on.');
        announcedOffRef.current = false;
      }
      return;
    }
    if (announcedOffRef.current) return;
    announcedOffRef.current = true;
    speak('Accessibility is off, so AdaptiveAI cannot see the screen. Open Settings to turn it on.');
  }, [status, speak]);

  // Background assist session: the microphone foreground service keeps the process alive and
  // this loop keeps re-arming recognition, so the user can just speak — app foreground or not.
  useEffect(() => {
    if (!assistAvailable) return;
    if (!settings.backgroundListening) {
      sessionLoopRef.current?.stop();
      sessionLoopRef.current = null;
      // Stop the service too. If the toggle flipped while startAssistSession() was still
      // awaiting, the loop was never created, so this branch is the ONLY cleanup — without
      // it the microphone FGS (and its wake lock) survives "off" until the next toggle.
      void assist.stopAssistSession().catch(() => {});
      return;
    }
    let cancelled = false;
    void (async () => {
      const notifOk = await ensureNotificationPermission();
      if (cancelled) return;
      if (!notifOk) {
        // Non-fatal: the mic session still runs, but its ongoing notification — the only
        // visible proof the mic is on and its stop affordance — is hidden on Android 13+.
        push({
          kind: 'message',
          text: 'Notifications are blocked, so the listening session has no status-bar entry. Allow notifications for AdaptiveAI in system Settings.',
        });
      }
      try {
        await assist.startAssistSession();
      } catch {
        push({ kind: 'error', text: 'Could not start the background listening session.' });
        return;
      }
      if (cancelled) {
        // The effect was torn down (setting flipped / language changed) while the session
        // was starting. The loop never starts, so nothing else will ever stop it — the
        // microphone FGS would keep running with no UI left to turn it off.
        void assist.stopAssistSession().catch(() => {});
        return;
      }
      sessionLoopRef.current = startAssistLoop(
        { language: settings.language, preferOnDeviceStt: settings.preferOnDeviceStt },
        {
          onPartial: (text) => setPartial(text),
          onFinal: (text) => {
            setPartial('');
            // Guard rails: ignore noise and never stack runs.
            if (runningRef.current) {
              push({ kind: 'status', text: `Heard "${text}" while busy — ignored.` });
              return;
            }
            const isShortcut = isDangerUtterance(text) || NOTE_PATTERN.test(text) || SCREEN_ASK_PATTERN.test(text);
            // A confirm dialog is open. Danger still pre-empts (runSos has its own latch).
            // Anything else is a spoken ANSWER to the dialog — a blind user cannot tap the
            // modal, so their "yes"/"do it"/"go ahead" approves it and "no"/"don't"/"cancel"
            // dismisses it. This is what lets a delegated task move forward by voice.
            if (pendingConfirmRef.current && !isDangerUtterance(text)) {
              const answer = text.trim().toLocaleLowerCase();
              const yes = /\b(yes|yeah|yep|do it|go ahead|ok|okay|allow|approve|confirm|sure|fine|please)\b/.test(answer);
              const no = /\b(no|nope|don't|dont|cancel|nevermind|never mind|stop|deny|decline|not now)\b/.test(answer);
              if (yes) {
                speak('OK, continuing.');
                clearPending(true);
              } else if (no) {
                speak('Cancelled.');
                clearPending(false);
              } else {
                // Ambiguous — repeat what the dialog is asking for so the user can answer yes/no.
                push({ kind: 'status', text: `Heard "${text}" — say yes or no to ${pendingConfirmRef.current.label}.` });
                speak(`Say yes or no to ${pendingConfirmRef.current.label}.`);
              }
              return;
            }
            const words = text.trim().split(/\s+/).length;
            // Allow short actionable voice commands ("add eggs", "open cart", "buy milk") as well
            // as full sentences — a real shopping flow is incremental, not one long monologue.
            const hasVerb = /\b(add|buy|order|get|open|find|search|show|put|place|type|send|go|tap|click|scroll|cart)\b/i.test(text);
            if (words < 3 && !isShortcut && !hasVerb) {
              push({ kind: 'status', text: `Heard "${text}" — I need a little more detail to act on it.` });
              speak(`I heard "${text}", but I need a little more detail.`);
              return;
            }
            void runRef.current(text).catch((e) => console.warn('[assistant] run failed:', e));
          },
          onFatal: (message) => {
            push({ kind: 'error', text: `Background listening stopped: ${message}` });
            sessionLoopRef.current = null;
          },
        },
      );
    })();
    return () => {
      cancelled = true;
      sessionLoopRef.current?.stop();
      sessionLoopRef.current = null;
    };
    // run() is intentionally excluded: onFinal reads runRef.current, which always holds the
    // latest run closure even when this effect does not re-run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assistAvailable, settings.backgroundListening, settings.language, settings.preferOnDeviceStt, sessionNonce]);

  // If the system killed the process/service while the app was backgrounded, the FGS cannot
  // restart itself (microphone type cannot be promoted from the background) — so when the
  // app comes back to the foreground, restart the session if the loop is dead.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => {
      if (next !== 'active') return;
      if (!assistAvailable || !settings.backgroundListening) return;
      if (sessionLoopRef.current?.active()) return;
      setSessionNonce((n) => n + 1);
    });
    return () => sub.remove();
  }, [assistAvailable, settings.backgroundListening]);

  const runSos = useCallback(async () => {
    if (sosBusyRef.current) {
      speak('Emergency dialog already open.');
      return;
    }
    // SOS pre-empts an agent confirmation — never let the two overwrite each other's resolver.
    if (pendingConfirmRef.current?.kind === 'agent') {
      clearPending(false);
    }
    sosBusyRef.current = true;
    try {
    alertFeedback();
    const contacts = profile.careContacts ?? [];
    if (contacts.length === 0) {
      speak('No care contacts are saved yet. Open Tools to add one.');
      Alert.alert('No care contacts', 'Add a trusted contact in Tools first, then try again.', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Open Tools', onPress: () => router.push('/tools') },
      ]);
      return;
    }
    const label = describeSos(contacts);
    speak(`AdaptiveAI wants to ${label}. Use the dialog to allow or cancel.`);
    const approved = await new Promise<boolean>((resolve) => {
      setPending({ label, resolve, kind: 'sos' });
    });
    // Clear the dialog on EVERY path — otherwise the modal stays visible forever
    // (hardware back / approve) and blocks the whole screen. No-op when a button
    // already settled it; settles it if something else resolved the promise.
    clearPending(false);
    if (!approved) {
      speak('Emergency message cancelled.');
      return;
    }
    speak('Preparing the emergency message.');
    try {
      const message = await composeSosMessage({
        senderName: profile.displayName,
        note: null,
        includeLocation: true,
      });
      const opened = await sendSos(message, contacts);
      speak(
        opened > 0
          ? `The emergency message is ready to send for ${contacts.length} contact${contacts.length > 1 ? 's' : ''}. Press send in the messaging app.`
          : 'No messaging app was available. Use the share sheet to send it.',
      );
      push({ kind: 'message', text: `Emergency message prepared for ${contacts.length} contact(s).` });
    } catch (err) {
      push({ kind: 'error', text: `Emergency flow failed: ${err instanceof Error ? err.message : String(err)}` });
      speak('The emergency flow failed. Try the SOS button in Tools.');
    }
    } finally {
      sosBusyRef.current = false;
    }
  }, [profile.careContacts, profile.displayName, push, router, speak]);

  const onEvent = useCallback(
    async (event: AgentEvent) => {
      switch (event.type) {
        case 'status':
          push({ kind: 'status', text: event.text });
          break;
        case 'thinking':
          push({ kind: 'status', text: `Step ${event.step} — thinking` });
          setProgress((p) => ({ step: event.step, max: p?.max ?? settings.maxSteps }));
          break;
        case 'action':
          push({ kind: 'action', text: event.label });
          break;
        case 'observation':
          push({ kind: 'observation', text: event.detail, ok: event.ok });
          break;
        case 'message':
          push({ kind: 'message', text: event.text });
          break;
        case 'confirm':
          // The modal is visual only — a blind user would never know it appeared. Speak it.
          // NEVER overwrite a live dialog: replacing the resolver strands the first await
          // forever (that is exactly how the SOS button bricked itself). Deny this request
          // and leave the user's open decision alone.
          if (pendingConfirmRef.current) {
            push({ kind: 'status', text: `Denied while a dialog is open: ${event.label}` });
            event.resolve(false);
            break;
          }
          speak(`AdaptiveAI wants to ${event.label}. Use the dialog to allow or cancel.`);
          setPending({ label: event.label, resolve: event.resolve, kind: 'agent' });
          break;
        case 'done': {
          // The task may have moved to another app since the run started; record where it ended.
          let app = status?.foregroundApp ?? '';
          if (assistAvailable) {
            try {
              app = (await assist.getStatus()).foregroundApp;
            } catch {
              // Keep the last known foreground app.
            }
          }
          const record: TaskRecord = {
            id: nextId(),
            at: Date.now(),
            instruction: lastInstructionRef.current,
            status: event.status,
            summary: event.summary,
            steps: event.steps,
            app,
          };
          recordTask(record);
          if (event.status === 'completed' && lastInstructionRef.current) {
            recordFrequentTask(lastInstructionRef.current);
          }
          setRunning(false);
          setProgress(null);
          // Settle a lingering agent confirm (the run is over, nobody will answer it).
          // A live SOS dialog has its own lifecycle and must not be cancelled from here.
          if (pendingConfirmRef.current?.kind !== 'sos') clearPending(false);
          console.log(
            `[agent] done status=${event.status} steps=${event.steps} summary=${(event.summary ?? '').slice(0, 120)}`,
          );
          break;
        }
      }
    },
    [push, speak, status?.foregroundApp, settings.maxSteps],
  );

  const run = useCallback(
    async (instruction: string) => {
      const text = instruction.trim();
      if (!text) return;
      // Danger pre-empts everything — abort the current run so SOS is never blocked.
      if (isDangerUtterance(text)) {
        if (runningRef.current) {
          runTokenRef.current += 1;
          abortRef.current?.abort();
          abortRef.current = null;
          runningRef.current = false;
          setRunning(false);
        }
        void runSos();
        return;
      }
      if (NOTE_PATTERN.test(text)) {
        speak('Opening Tools to record the emergency note.');
        router.push({ pathname: '/tools', params: { record: '1' } });
        return;
      }
      // A dialog is already open. Starting a second run would overwrite its resolver and
      // strand the first await forever — that is what permanently bricked the SOS button.
      // (Danger and notes are handled above, so SOS still pre-empts an open dialog.)
      // A spoken or typed yes/no here ANSWERS the open dialog instead (a blind user cannot
      // tap a modal that may even be invisible over another app).
      if (pendingConfirmRef.current) {
        const answer = text.toLocaleLowerCase();
        if (/\b(yes|yeah|yep|do it|go ahead|ok|okay|allow|approve|confirm|sure|fine|please)\b/.test(answer)) {
          speak('OK, continuing.');
          clearPending(true);
        } else if (/\b(no|nope|don't|dont|cancel|nevermind|never mind|stop|deny|decline|not now)\b/.test(answer)) {
          speak('Cancelled.');
          clearPending(false);
        } else {
          push({ kind: 'status', text: 'A dialog is open — answer it first.' });
          speak('Please answer the open dialog first.');
        }
        return;
      }
      if (runningRef.current) {
        push({ kind: 'status', text: 'Busy — wait for the current task to finish.' });
        speak('Busy — wait for the current task to finish.');
        return;
      }
      // "What is on my screen?" — local tree first, Gemini vision only if needed.
      if (SCREEN_ASK_PATTERN.test(text)) {
        runningRef.current = true;
        setRunning(true);
        setLog([]);
        push({ kind: 'status', text: 'Reading screen…' });
        const controller = new AbortController();
        const runToken = ++runTokenRef.current;
        abortRef.current = controller;
        try {
          const desc = await describeScreen({ geminiApiKey, settings, profile, signal: controller.signal });
          if (runTokenRef.current !== runToken) return;
          push({ kind: 'message', text: desc.spoken });
          speak(desc.spoken);
          recordTask({
            id: nextId(),
            at: Date.now(),
            instruction: text,
            status: 'completed',
            summary: desc.spoken,
            steps: 1,
            app: desc.app,
          });
        } catch (err) {
          if (runTokenRef.current !== runToken || controller.signal.aborted) return;
          const msg = err instanceof Error ? err.message : String(err);
          push({ kind: 'error', text: msg, ok: false });
          speak(`I could not read the screen. ${msg}`);
        } finally {
          if (runTokenRef.current === runToken) {
            runningRef.current = false;
            abortRef.current = null;
            setRunning(false);
          }
        }
        return;
      }

      if (!geminiApiKey) {
        Alert.alert(
          keyUncertain ? 'Could not read the stored key' : 'Gemini key needed',
          keyUncertain
            ? 'The secure key store did not answer. Your key may still be saved — reopen Settings to try again.'
            : 'AdaptiveAI uses Google Gemini Flash for reasoning. Add your free key in Settings first (aistudio.google.com).',
          [
            { text: 'Cancel', style: 'cancel' },
            { text: 'Open Settings', onPress: () => router.push('/settings') },
          ],
        );

        return;
      }
      // Always fresh-check: status may be stale after the user enabled it in system Settings.
      let a11yConfirmed = status?.accessibilityEnabled ?? false;
      try {
        const st = await assist.getStatus();
        a11yConfirmed = st.accessibilityEnabled;
        setStatus(st);
      } catch {
        a11yConfirmed = status?.accessibilityEnabled ?? false;
      }
      if (!a11yConfirmed) {
        Alert.alert(
          'Accessibility is off',
          'Without it AdaptiveAI cannot see or operate other apps. Turn it on in Settings.',
          [
            { text: 'Cancel', style: 'cancel' },
            { text: 'Open Settings', onPress: () => router.push('/settings') },
          ],
        );
        return;
      }

      lastInstructionRef.current = text;
      runningRef.current = true;
      setDraft('');
      setRunning(true);
      setProgress({ step: 0, max: settings.maxSteps });
      setLog([]);
      setPlanLine('');
      push({ kind: 'message', text: text });

      const controller = new AbortController();
      const runToken = ++runTokenRef.current;
      abortRef.current = controller;

      const finish = () => {
        if (runTokenRef.current !== runToken) return;
        runningRef.current = false;
        abortRef.current = null;
        setRunning(false);
        setProgress(null);
        // Settle, don't just hide: clearing state while the ref still holds a resolver
        // desyncs the two and strands whoever is awaiting that dialog.
        if (pendingConfirmRef.current?.kind !== 'sos') clearPending(false);
      };

      const onOrchestratorEvent = async (event: OrchestratorEvent) => {
        if (runTokenRef.current !== runToken) return;
        try {
        switch (event.type) {
          case 'plan':
            setPlanLine(event.text);
            push({ kind: 'plan', text: event.text });
            break;
          case 'status':
            push({ kind: 'status', text: event.text });
            break;
          case 'speak':
            speak(event.text);
            break;
          case 'agent-event': {
            // Sub-step agent `done` must NOT clear running/record a task — the overall
            // goal finishes only on orchestrator `done`, or Stop disappears mid-run.
            const inner = event.event;
            if (inner.type === 'done') {
              push({ kind: 'message', text: inner.summary });
              break;
            }
            void onEvent(inner);
            break;
          }
          case 'done': {
            push({ kind: 'message', text: event.summary });
            // Record the overall goal (sub-steps are not separate tasks).
            let app = status?.foregroundApp ?? '';
            try { app = (await assist.getStatus()).foregroundApp; } catch {}
            recordTask({
              id: nextId(),
              at: Date.now(),
              instruction: text,
              status: 'completed',
              summary: event.summary,
              steps: 0,
              app,
            });
            recordFrequentTask(text);
            finish();
            break;
          }
        }
        } catch {}
      };

      try {
        if (settings.useOrchestrator && geminiApiKey) {
          await runOrchestrated({
            goal: text,
            geminiApiKey,
            settings,
            profile,
            onEvent: onOrchestratorEvent,
            signal: controller.signal,
          });
        } else {
          await runAgent({
            instruction: text,
            geminiApiKey,
            settings,
            profile,
            onEvent: (event) => {
              if (runTokenRef.current === runToken) void onEvent(event);
            },
            signal: controller.signal,
          });
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        if (runTokenRef.current === runToken) {
          push({ kind: 'error', text: message, ok: false });
          recordTask({
            id: nextId(),
            at: Date.now(),
            instruction: text,
            status: controller.signal.aborted ? 'cancelled' : 'failed',
            summary: message,
            steps: 0,
            app: status?.foregroundApp ?? '',
          });
        }
      } finally {
        finish();
      }
    },
    [
      keyUncertain,
      geminiApiKey,
      onEvent,
      profile,
      push,
      router,
      runSos,
      speak,
      status?.accessibilityEnabled,
      status?.foregroundApp,
      settings,
    ],
  );

  // The assist loop's onFinal reads runRef.current, so it must see the latest run closure even
  // when the loop effect itself does not re-run (e.g. after the user enables accessibility or
  // saves a Gemini key).
  useEffect(() => {
    runRef.current = run;
  }, [run]);

  useEffect(() => {
    const task = typeof params.task === 'string' ? params.task.trim() : '';
    if (!task) return;
    void run(task).catch((e) => console.warn('[assistant] run failed:', e));
    router.setParams({ task: undefined, nonce: undefined });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.task, params.nonce]);

  const onMicPress = useCallback(async () => {
    if (runningRef.current) {
      push({ kind: 'status', text: 'Busy — wait for the current task to finish.' });
      return;
    }
    if (listening) {
      // Deliberate cancel: mark it so the resulting recognizer error is not logged as a failure.
      cancelledVoiceRef.current = true;
      setListening(false);
      setPartial('');
      await assist.cancelVoice().catch(() => {});
      return;
    }
    cancelledVoiceRef.current = false;
    // The background loop re-arms the singleton recognizer roughly every second; if it is
    // still running it calls startVoice mid-listen and kills this session (the mic tap
    // then fails with a stale error). Pause it for the duration of the tap — the loop
    // keeps its own handlers and resumes when we release the hold.
    const loop = sessionLoopRef.current;
    const loopWasActive = loop?.active() ?? false;
    if (loopWasActive) setVoiceHold(true);
    try {
      let granted = false;
      try {
        granted = await ensureMicPermission();
      } catch {
        granted = false;
      }
      if (!granted) {
        Alert.alert('Microphone blocked', 'Allow microphone access in app settings to use voice.', [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Open app settings', onPress: () => assist.openAppSettings().catch(() => {}) },
        ]);
        return;
      }
      setListening(true);
      setPartial('');
      try {
        const heard = await listenOnce(settings);
        // Hand the mic UI back before the possibly long agent run starts.
        setListening(false);
        setPartial('');
        if (heard.trim()) await run(heard);
      } catch (err) {
        if (!cancelledVoiceRef.current) {
          push({ kind: 'error', text: err instanceof Error ? err.message : String(err), ok: false });
        }
      } finally {
        setListening(false);
        cancelledVoiceRef.current = false;
      }
    } finally {
      // MUST run on every path (including a denied permission) or the background
      // loop stays paused forever and background listening silently dies.
      if (loopWasActive) setVoiceHold(false);
    }
  }, [listening, push, run, settings]);

  useEffect(() => {
    if (!assistAvailable) return;
    return subscribeVoice({
      onPartial: (text: string) => setPartial(text),
    });
  }, []);

  const stop = useCallback(() => {
    runTokenRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    runningRef.current = false;
    // Resolve the agent confirm only (never SOS) — SOS has its own lifecycle.
    if (pendingConfirmRef.current?.kind !== 'sos') clearPending(false);
    setRunning(false);
    setProgress(null);
    push({ kind: 'status', text: 'Stopped.' });
  }, [push]);

  // Pulsing ring on the mic orb while listening — visible + haptic feedback for eyes-free use.
  const pulse = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!listening) {
      pulse.setValue(0);
      return;
    }
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 900, easing: Easing.out(Easing.quad), useNativeDriver: false }),
        Animated.timing(pulse, { toValue: 0, duration: 900, easing: Easing.in(Easing.quad), useNativeDriver: false }),
      ]),
    );
    anim.start();
    return () => anim.stop();
  }, [listening, pulse]);
  const ringScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 1.35] });
  const ringOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.5, 0] });

  const sizes = useMemo(
    () =>
      StyleSheet.create({
        body: { fontSize: scaled(15, u), lineHeight: scaled(21, u) },
        caption: { fontSize: scaled(12, u), lineHeight: scaled(17, u) },
        heroLine: { fontSize: scaled(16, u), lineHeight: scaled(23, u) },
      }),
    [u],
  );

  const frequentTasks = profile.frequentTasks ?? [];

  if (!assistAvailable) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: theme.bg }} edges={['top']}>
        <View style={styles.centered}>
          <Card>
            <Text style={[sizes.body, { color: theme.text, fontWeight: '700' }]}>
              Native layer missing
            </Text>
            <Text style={[sizes.caption, { color: theme.textDim, marginTop: 8 }]}>
              This build has no AdaptiveAssist module, so it cannot read the screen or act on other
              apps. Install the release APK built from this project instead of a debug build served
              by Metro.
            </Text>
          </Card>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.bg }} edges={['top']}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={[styles.topBar, { borderBottomColor: theme.border }]}>
          <Text
            accessibilityRole="header"
            style={[styles.title, { color: theme.text, fontSize: scaled(24, u) }]}
          >
            AdaptiveAI
          </Text>
          <View style={styles.pills}>
            <Pill
              text={status == null ? 'A11Y …' : status.accessibilityEnabled ? 'A11Y ON' : 'A11Y OFF'}
              tone={status == null ? 'warn' : status.accessibilityEnabled ? 'ok' : 'danger'}
            />
            <Pill
              text={
                geminiApiKey
                  ? settings.useOrchestrator
                    ? 'GEMINI + PLANNER'
                    : 'GEMINI READY'
                  : keyUncertain
                    ? 'KEY UNKNOWN'
                    : 'NO KEY'
              }
              tone={geminiApiKey ? 'ok' : 'warn'}
            />
            {settings.backgroundListening ? (
              <Pill
                text={status?.assistSession ? 'BG LISTENING' : 'BG OFF'}
                tone={status?.assistSession ? 'ok' : 'warn'}
              />
            ) : null}
          </View>
        </View>

        <FlatList
          ref={listRef}
          data={log}
          keyExtractor={(item) => item.id}
          style={styles.flex}
          contentContainerStyle={styles.logContent}
          ListEmptyComponent={
            <View style={styles.hero}>
              <Animated.View
                pointerEvents="none"
                style={[
                  styles.orbRing,
                  { backgroundColor: theme.accentSoft, transform: [{ scale: ringScale }], opacity: ringOpacity },
                ]}
              />
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={listening ? 'Stop listening' : 'Start voice task'}
                accessibilityState={{ busy: listening || running }}
                onPress={onMicPress}
                disabled={running}
                style={({ pressed }) => [
                  styles.heroMic,
                  {
                    backgroundColor: listening ? theme.danger : theme.accent,
                    opacity: running ? 0.4 : pressed ? 0.85 : 1,
                    ...elevation,
                  },
                ]}
              >
                <Ionicons
                  name={listening ? 'stop' : 'mic'}
                  size={scaled(38, u)}
                  color={listening ? theme.onDanger : theme.accentText}
                />
              </Pressable>
              <Text style={[sizes.heroLine, { color: theme.text, textAlign: 'center', marginTop: SPACE.lg, fontWeight: '600' }]}>
                {listening ? 'Listening… speak now' : 'Tap the mic, then say what you want done.'}
              </Text>
              <Text style={[sizes.caption, { color: theme.textDim, textAlign: 'center', marginTop: SPACE.sm }]}>
                “open the browser and search for trains to Mumbai” · “fill the sign-up form with my
                details”
              </Text>

              {frequentTasks.length > 0 ? (
                <View style={styles.chipWrap}>
                  <Text style={[sizes.caption, { color: theme.textDim, marginTop: SPACE.lg, marginBottom: SPACE.sm }]}>
                    YOUR USUAL TASKS
                  </Text>
                  <View style={styles.chipRow}>
                    {frequentTasks.slice(0, 4).map((t) => (
                      <Chip
                        key={t.phrase}
                        label={t.phrase.length > 34 ? `${t.phrase.slice(0, 33)}…` : t.phrase}
                        icon="repeat"
                        onPress={() => void run(t.phrase)}
                      />
                    ))}
                  </View>
                </View>
              ) : null}

              <View style={styles.chipWrap}>
                <Text style={[sizes.caption, { color: theme.textDim, marginTop: SPACE.lg, marginBottom: SPACE.sm }]}>
                  QUICK START
                </Text>
                <View style={styles.chipRow}>
                  <Chip label="Order groceries" icon="cart" onPress={() => void run('Order my groceries on Zepto.')} />
                  <Chip label="Shop on Amazon" icon="cart" onPress={() => void run('Open Amazon and search for what I describe. Fill the form with my saved details and ask me before payment.')} />
                  <Chip label="Watch on YouTube" icon="play" onPress={() => void run('Open YouTube and search for what I describe.')} />
                  <Chip label="Book movie" icon="ticket" onPress={() => void run('Open BookMyShow and help me book a movie. Fill the form with my saved details and ask me before payment, login, or CAPTCHA.')} />
                  <Chip label="Identify a product" icon="camera" onPress={() => router.push('/tools')} />
                  <Chip label="Send emergency" icon="warning" onPress={() => void runSos()} />
                </View>
              </View>

              <Text style={[sizes.caption, { color: theme.textDim, textAlign: 'center', marginTop: SPACE.xl }]}>
                Screen reading, voice and gestures run on this phone. Reasoning goes to Google Gemini Flash (free tier). Say “What is on my screen?” any time.
              </Text>
            </View>
          }
          renderItem={({ item }) => (
            <View
              accessibilityLiveRegion="polite"
              style={[
                styles.logRow,
                {
                  borderLeftColor:
                    item.kind === 'error'
                      ? theme.danger
                      : item.kind === 'action'
                        ? theme.accent
                        : item.kind === 'plan'
                          ? theme.ok
                          : item.kind === 'observation'
                            ? item.ok
                              ? theme.ok
                              : theme.warn
                            : theme.border,
                },
              ]}
            >
              <Text
                style={[
                  sizes.body,
                  {
                    color:
                      item.kind === 'message'
                        ? theme.text
                        : item.kind === 'plan'
                          ? theme.ok
                          : item.kind === 'error'
                            ? theme.danger
                            : theme.textDim,
                    fontWeight: item.kind === 'message' || item.kind === 'action' || item.kind === 'plan' ? '600' : '400',
                  },
                ]}
              >
                {item.text}
              </Text>
            </View>
          )}
          onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
        />

        {running && progress ? (
          <View
            accessibilityLiveRegion="polite"
            style={[styles.progressWrap, { backgroundColor: theme.surface, borderTopColor: theme.border }]}
          >
            <ProgressBar ratio={progress.max > 0 ? progress.step / progress.max : 0} />
            <Text style={[sizes.caption, { color: theme.textDim, marginTop: 6 }]} numberOfLines={1}>
              {planLine ? `Plan: ${planLine}` : 'Working…'}
            </Text>
          </View>
        ) : null}

        {partial ? (
          <View
            accessibilityLiveRegion="polite"
            style={[styles.partialBar, { backgroundColor: theme.surfaceAlt }]}
          >
            <View style={[styles.partialDot, { backgroundColor: listening ? theme.danger : theme.accent }]} />
            <Text style={[sizes.body, { color: theme.text, flex: 1 }]} numberOfLines={2}>
              {partial}
            </Text>
          </View>
        ) : null}

        <View style={[styles.inputBar, { borderTopColor: theme.border, backgroundColor: theme.surface }]}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={listening ? 'Stop listening' : 'Start voice task'}
            accessibilityState={{ busy: listening }}
            onPress={onMicPress}
            disabled={running}
            style={({ pressed }) => [
              styles.micButton,
              {
                backgroundColor: listening ? theme.danger : theme.accent,
                borderRadius: theme.radius,
                opacity: running ? 0.4 : pressed ? 0.85 : 1,
              },
            ]}
          >
            <Ionicons name={listening ? 'stop' : 'mic'} size={26} color={listening ? theme.onDanger : theme.accentText} />
          </Pressable>

          <TextInput
            value={draft}
            onChangeText={setDraft}
            placeholder={listening ? 'Listening…' : 'Type a task…'}
            placeholderTextColor={theme.textDim}
            accessibilityLabel="Task text"
            editable={!running}
            onSubmitEditing={() => run(draft)}
            returnKeyType="go"
            style={[
              styles.textInput,
              {
                backgroundColor: theme.surfaceAlt,
                borderColor: theme.border,
                borderRadius: theme.radius,
                color: theme.text,
                fontSize: sizes.body.fontSize,
              },
            ]}
          />

          {running ? (
            <Button label="Stop" variant="danger" icon="stop" onPress={stop} style={styles.sendButton} />
          ) : (
            <Button
              label="Go"
              icon="arrow-forward"
              onPress={() => run(draft)}
              disabled={!draft.trim()}
              style={styles.sendButton}
            />
          )}
        </View>
      </KeyboardAvoidingView>

      <Modal
        visible={Boolean(pendingConfirm)}
        transparent
        animationType="fade"
        onRequestClose={() => clearPending(false)}
      >
        <View style={[styles.modalBackdrop, { backgroundColor: theme.backdrop }]}>
          <View
            style={[
              styles.modalCard,
              { backgroundColor: theme.surface, borderRadius: theme.radius, borderColor: theme.border },
              elevation,
            ]}
          >
            <Ionicons name="hand-left" size={26} color={theme.accent} style={{ marginBottom: 8 }} />
            <Text style={[sizes.caption, { color: theme.textDim }]}>AdaptiveAI wants to</Text>
            <Text style={[styles.modalTitle, { color: theme.text, fontSize: scaled(19, u) }]}>
              {pendingConfirm?.label ?? ''}
            </Text>
            <Text style={[sizes.caption, { color: theme.textDim, marginTop: 6 }]}>
              Nothing happens until you choose.
            </Text>
            <View style={styles.modalButtons}>
              <Button
                label="Don't"
                variant="secondary"
                icon="close"
                style={styles.modalButton}
                onPress={() => clearPending(false)}
              />
              <Button
                label="Do it"
                icon="checkmark"
                style={styles.modalButton}
                onPress={() => clearPending(true)}
              />
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  centered: { alignItems: 'center', justifyContent: 'center', padding: SPACE.xl, flex: 1 },
  topBar: {
    paddingHorizontal: SPACE.lg,
    paddingTop: SPACE.md,
    paddingBottom: 12,
    borderBottomWidth: 1,
  },
  title: { fontWeight: '800', letterSpacing: -0.5 },
  pills: { flexDirection: 'row', gap: 8, marginTop: 10, flexWrap: 'wrap' },
  hero: { alignItems: 'center', padding: SPACE.xl, paddingTop: SPACE.xl + 10 },
  orbRing: {
    position: 'absolute',
    width: 148,
    height: 148,
    borderRadius: 74,
    top: 6,
  },
  heroMic: {
    width: 128,
    height: 128,
    borderRadius: 64,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chipWrap: { alignSelf: 'stretch' },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm, justifyContent: 'center' },
  logContent: { padding: 16, paddingBottom: 24 },
  logRow: { borderLeftWidth: 3, paddingLeft: 11, paddingVertical: 6, marginBottom: 4 },
  progressWrap: {
    paddingHorizontal: SPACE.lg,
    paddingVertical: 10,
    borderTopWidth: 1,
  },
  partialBar: {
    paddingHorizontal: SPACE.lg,
    paddingVertical: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  partialDot: { width: 10, height: 10, borderRadius: 5 },
  inputBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: SPACE.md + 2,
    paddingVertical: 12,
    borderTopWidth: 1,
  },
  micButton: {
    width: 56,
    height: 56,
    alignItems: 'center',
    justifyContent: 'center',
  },
  textInput: { flex: 1, minHeight: 52, paddingHorizontal: 14, borderWidth: 1 },
  sendButton: { minWidth: 72 },
  modalBackdrop: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 26,
  },
  modalCard: { padding: 22, borderWidth: 1, width: '100%', maxWidth: 420 },
  modalTitle: { fontWeight: '700', marginTop: 7, lineHeight: 26 },
  modalButtons: { flexDirection: 'row', gap: 12, marginTop: 22 },
  modalButton: { flex: 1 },
});
