import React, { useCallback, useState } from 'react';
import { useFocusEffect } from 'expo-router';
import {
  Alert,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { assist, assistAvailable, ensureMicPermission } from '../../src/native/assist';
import type { AssistStatus } from '../../src/native/assist';
import { GEMINI_BASE_URL, GEMINI_MODEL_CHOICES, testApiKey } from '../../src/services/gemini';
import {
  noteCorrection,
  setGeminiApiKey,
  updateProfile,
  updateSavedFields,
  updateSettings,
  useGeminiApiKey,
  useHasUserKey,
  useProfile,
  useSettings,
} from '../../src/services/profile';
import type { AccessibilityNeed } from '../../src/services/profile';
import { useTheme } from '../../src/ui/AppProviders';
import {
  Button,
  Card,
  Header,
  Pill,
  Row,
  SectionTitle,
  TextField,
  Toggle,
} from '../../src/ui/components';
import { useSpeak } from '../../src/ui/useSpeak';
import { scaled } from '../../src/theme';

const NEEDS: { value: AccessibilityNeed; label: string }[] = [
  { value: 'none', label: 'None' },
  { value: 'blind', label: 'Blind' },
  { value: 'low_vision', label: 'Low vision' },
  { value: 'cognitive', label: 'Cognitive' },
  { value: 'motor', label: 'Motor' },
  { value: 'deaf_hard_of_hearing', label: 'Deaf / HoH' },
];

const SPEECH_LANGUAGES: { code: string; label: string }[] = [
  { code: 'en-US', label: 'English (US)' },
  { code: 'en-GB', label: 'English (UK)' },
  { code: 'hi-IN', label: 'हिन्दी' },
  { code: 'es-ES', label: 'Español' },
  { code: 'fr-FR', label: 'Français' },
  { code: 'de-DE', label: 'Deutsch' },
];

export default function SettingsTab() {
  const theme = useTheme();
  const settings = useSettings();
  const profile = useProfile();
  const storedKey = useGeminiApiKey();
  const hasUserKey = useHasUserKey();
  const speak = useSpeak();
  const u = profile.uiScale;

  const [keyDraft, setKeyDraft] = useState('');
  const [revealKey, setRevealKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [status, setStatus] = useState<AssistStatus | null>(null);
  const [correctionNote, setCorrectionNote] = useState('');

  const refresh = useCallback(async () => {
    if (!assistAvailable) return;
    try {
      setStatus(await assist.getStatus());
    } catch {
      setStatus(null);
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  useFocusEffect(
    useCallback(() => {
      void refresh();
    }, [refresh]),
  );

  const saveKey = useCallback(async () => {
    const next = keyDraft.trim();
    if (!next) {
      speak('Nothing to save. Paste a Gemini API key first, free at aistudio.google.com.');
      Alert.alert('Nothing to save', 'Paste a Gemini API key first (free at aistudio.google.com).');
      return;
    }
    if (next.length < 20 || /\s/.test(next)) {
      speak('That does not look right. A Gemini key has no spaces and is longer than 20 characters. Check and try again.');
      Alert.alert('That does not look right', 'A Gemini key has no spaces and is longer than 20 characters. Check and try again.');
      return;
    }
    const ok = await setGeminiApiKey(next);
    if (ok) {
      setKeyDraft('');
      setTestResult({ ok: true, text: 'Key saved to the secure key store.' });
      speak('Key saved to the secure key store.');
    } else {
      speak('The key could not be saved to the key store. Try again.');
      setTestResult({ ok: false, text: 'The key could not be saved to the key store. Try again.' });
    }
  }, [keyDraft, speak]);

  const test = useCallback(async () => {
    const candidate = keyDraft.trim() || storedKey;
    if (!candidate) {
      speak('No key. Paste your Gemini API key first.');
      Alert.alert('No key', 'Paste your Gemini API key first.');
      return;
    }
    if (candidate.length < 20 || /\s/.test(candidate)) {
      speak('That does not look right. A Gemini key has no spaces and is longer than 20 characters.');
      Alert.alert('That does not look right', 'A Gemini key has no spaces and is longer than 20 characters.');
      return;
    }
    setTesting(true);
    setTestResult(null);
    speak('Testing the key. This can take a few seconds.');
    const started = Date.now();
    try {
      const result = await testApiKey(candidate);
      const ms = Date.now() - started;
      if (result.ok) {
        let savedNote = '';
        if (keyDraft.trim() && candidate !== storedKey) {
          const saved = await setGeminiApiKey(candidate);
          if (!saved) {
            const text = 'Key works, but could not be saved to the key store. Check Settings again.';
            setTestResult({ ok: false, text });
            speak(text);
            return;
          }
          savedNote = ' Saved to key store.';
        }
        const text = `Key accepted. ${result.modelCount} models visible in ${ms} ms.${savedNote} Free quota is capped — if you hit 429, wait a minute.`;
        setTestResult({ ok: true, text });
        speak(`Key accepted. ${result.modelCount} models visible. The key is working.`);
      } else {
        setTestResult({ ok: false, text: result.error });
        speak(`Key test failed. ${result.error}`);
      }
    } catch (err) {
      const text = `Test failed: ${err instanceof Error ? err.message : String(err)}`;
      setTestResult({ ok: false, text });
      speak(text);
    } finally {
      setTesting(false);
    }
  }, [keyDraft, storedKey, speak]);

  const requestMic = useCallback(async () => {
    let ok = false;
    try { ok = await ensureMicPermission(); } catch { ok = false; }
    speak(ok ? 'Microphone allowed.' : 'Microphone still blocked. Open app settings below to allow it.');
    Alert.alert(ok ? 'Microphone allowed' : 'Microphone still blocked', ok ? '' : 'Open app settings below to allow it.', [
      { text: 'OK', style: 'cancel' },
      ...(!ok ? [{ text: 'Open app settings', onPress: () => assist.openAppSettings().catch(() => {}) }] : []),
    ]);
  }, [speak]);

  const addCorrection = useCallback(() => {
    const note = correctionNote.trim();
    if (!note) {
      speak('Type an instruction first.');
      return;
    }
    noteCorrection('general instruction', note);
    setCorrectionNote('');
    speak('Saved. AdaptiveAI will follow this from now on.');
    Alert.alert('Saved', 'AdaptiveAI will follow this from now on.');
  }, [correctionNote, speak]);

  const body = { fontSize: scaled(15, u) };
  const caption = { fontSize: scaled(12, u), lineHeight: scaled(17, u) };

  return (
    <SafeAreaView style={[styles.flex, { backgroundColor: theme.bg }]} edges={['top']}>
      <Header title="Settings" subtitle="Everything here stays on this device" />

      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <SectionTitle>GOOGLE GEMINI (FREE TIER)</SectionTitle>
        <Card>
          <Text style={[caption, { color: theme.textDim, marginBottom: 12 }]}>
            Your key is stored in the Android Keystore and sent only to {GEMINI_BASE_URL.replace('https://', '').split('/')[0]}. There is no AdaptiveAI server in between.
            Free quota is real but capped (~15 requests/min, daily cap). The app tells you honestly when you hit it.
            Screen reading, gestures, speech and notes run on-device without any key.
          </Text>
          <TextField
            label={revealKey ? 'API key (visible)' : 'API key (hidden)'}
            value={keyDraft}
            onChangeText={(t) => setKeyDraft(t)}
            placeholder={hasUserKey ? maskKey(storedKey) : 'AIza… (paste your own key)'}
            autoCapitalize="none"
            secure={!revealKey}
          />
          {hasUserKey ? (
            <Text style={[caption, { color: theme.textDim, marginTop: 8 }]}>
              Saved key: {revealKey ? storedKey : maskKey(storedKey)}
            </Text>
          ) : (
            <Text style={[caption, { color: theme.textDim, marginTop: 8 }]}>
              No saved key — using the key embedded in this build (never shown here). Paste your own key above to use yours instead.
            </Text>
          )}
          <View style={styles.buttonRow}>
            <Button label="Save key" onPress={saveKey} style={styles.grow} />
            <Button
              label="Test"
              variant="secondary"
              onPress={test}
              busy={testing}
              style={styles.grow}
            />
            <Button
              label={revealKey ? 'Hide' : 'Show'}
              variant="ghost"
              onPress={() => setRevealKey((v) => !v)}
            />
          </View>
          {hasUserKey ? (
            <Button
              label="Remove saved key"
              variant="ghost"
              onPress={() => {
                speak('Remove the saved key? Confirm in the dialog.');
                Alert.alert('Remove saved key?', 'Your saved key will be deleted. The embedded build key will still work.', [
                  { text: 'Cancel', style: 'cancel' },
                  {
                    text: 'Remove',
                    style: 'destructive',
                    onPress: async () => {
                      try {
                        const ok = await setGeminiApiKey('');
                        if (ok) {
                          setKeyDraft('');
                          setTestResult(null);
                          speak('Your saved key was deleted. The build still has an embedded key, so the app keeps working.');
                          Alert.alert('Removed', 'Your saved key was deleted. The build still has an embedded key, so the app keeps working.');
                        } else {
                          speak('The saved key could not be removed. Try again.');
                        }
                      } catch (err) {
                        speak(`The saved key could not be removed. ${err instanceof Error ? err.message : String(err)}`);
                      }
                    },
                  },
                ]);
              }}
              style={{ marginTop: 8 }}
            />
          ) : (
            <Text style={[caption, { color: theme.textDim, marginTop: 8 }]}>
              Using the key embedded in this build. Paste your own key above to use yours instead.
            </Text>
          )}
          {testResult ? (
            <View
              accessibilityLiveRegion="polite"
              style={[styles.resultBox, { borderColor: testResult.ok ? theme.ok : theme.danger }]}
            >
              <Text style={[caption, { color: testResult.ok ? theme.ok : theme.danger }]}>
                {testResult.text}
              </Text>
            </View>
          ) : null}
          <Pressable
            accessibilityRole="link"
            accessibilityHint="Opens browser"
            onPress={() => Linking.openURL('https://aistudio.google.com/app/apikey').catch(() => {})}
            style={[styles.linkRow, { minHeight: 48, justifyContent: 'center', paddingVertical: 10 }]}
          >
            <Text style={[caption, { color: theme.accent }]}>
              Get a free key at aistudio.google.com/app/apikey
            </Text>
          </Pressable>
        </Card>

        <SectionTitle>Model</SectionTitle>
        <Card>
          <Text style={[caption, { color: theme.textDim, marginBottom: 10 }]}>
            Gemini Flash — fast, free-tier friendly, supports vision for screenshots and product scans.
            Screen reading itself is done on-device with Android AccessibilityService; Gemini is only
            called for reasoning and for screens the text tree cannot describe.
          </Text>
          <Chips
            options={[...GEMINI_MODEL_CHOICES]}
            value={settings.model}
            theme={theme}
            u={u}
            onChange={(v) => {
              updateSettings({ model: v });
              speak(`Model set to ${v}.`);
            }}
          />
          <Text style={[caption, { color: theme.textDim, marginTop: 14 }]}>
            Max steps per task: {settings.maxSteps}
          </Text>
          <Stepper
            value={settings.maxSteps}
            min={3}
            max={30}
            name="max steps"
            theme={theme}
            onChange={(v) => {
              updateSettings({ maxSteps: v });
              speak(`Maximum steps set to ${v}.`);
            }}
          />
        </Card>

        <SectionTitle>Permissions</SectionTitle>
        <Card style={styles.flush}>
          <Row
            label="Accessibility"
            value={
              status?.accessibilityEnabled
                ? 'On — AdaptiveAI can read and operate other apps'
                : 'Off — nothing will work until this is on'
            }
            onPress={() => {
              speak(
                status?.accessibilityEnabled
                  ? 'Accessibility is on. AdaptiveAI can read and operate other apps.'
                  : 'Accessibility is off. Nothing will work until this is on. Opening accessibility settings.',
              );
              assist.openAccessibilitySettings().catch(() => {});
            }}
            right={
              <Pill
                text={status?.accessibilityEnabled ? 'ON' : 'OFF'}
                tone={status?.accessibilityEnabled ? 'ok' : 'danger'}
              />
            }
          />
          <Row
            label="Microphone"
            value="Needed for voice tasks"
            onPress={requestMic}
            right={<Text style={[body, { color: theme.accent }]}>Grant</Text>}
          />
          <Row
            label="App settings"
            value="All permissions for AdaptiveAI"
            onPress={() => assist.openAppSettings().catch(() => {})}
          />
          <Row
            label="Speech recognition"
            value={
              status?.lastListenOnDevice
                ? 'Last listen used the offline recognizer'
                : status?.sttAvailable
                  ? 'System recognizer (offline not confirmed on this device)'
                  : 'No recognizer installed'
            }
            right={
              <Pill
                text={
                  status?.lastListenOnDevice ? 'OFFLINE' : status?.sttAvailable ? 'SYSTEM' : 'NONE'
                }
                tone={status?.lastListenOnDevice ? 'ok' : status?.sttAvailable ? 'warn' : 'danger'}
              />
            }
          />
        </Card>

        <SectionTitle>Voice &amp; safety</SectionTitle>
        <Card style={styles.flush}>
          <Toggle
            label="Speak responses"
            description="Read results and questions out loud"
            value={settings.speakResponses}
            onValueChange={(v) => {
              updateSettings({ speakResponses: v });
              if (v) {
                void assist
                  .speak('Speak responses is on. I will read results and questions out loud.', settings.speechRate, settings.language)
                  .catch(() => {});
              }
            }}
          />
          <Toggle
            label="Prefer offline speech"
            description="Use the on-device recognizer when one is installed"
            value={settings.preferOnDeviceStt}
            onValueChange={(v) => updateSettings({ preferOnDeviceStt: v })}
          />
          <View style={styles.padded}>
            <Text style={[caption, { color: theme.textDim, marginBottom: 8 }]}>
              Speech language
            </Text>
            <Chips
              options={SPEECH_LANGUAGES.map((l) => l.code)}
              labels={Object.fromEntries(SPEECH_LANGUAGES.map((l) => [l.code, l.label]))}
              value={settings.language}
              theme={theme}
              u={u}
              onChange={(v) => updateSettings({ language: v })}
            />
          </View>
          <Toggle
            label="Confirm before acting"
            description="Ask before tapping, typing or opening another app"
            value={settings.confirmBeforeActing}
            onValueChange={(v) => updateSettings({ confirmBeforeActing: v })}
          />
          <Toggle
            label="Use vision screenshots"
            description="Let the model look at real pixels, not just the element tree"
            value={settings.useVisionWhenAvailable}
            onValueChange={(v) => updateSettings({ useVisionWhenAvailable: v })}
          />
          <Toggle
            label="Plan tasks before acting"
            description="Break the goal into steps first (one extra Gemini call; off saves quota)"
            value={settings.useOrchestrator}
            onValueChange={(v) => updateSettings({ useOrchestrator: v })}
          />
          <Toggle
            label="Listen in background"
            description={
              Platform.OS === 'android' && Platform.Version >= 34
                ? 'Keep voice working in other apps or with the screen off (uses a persistent notification and more battery)'
                : 'Keep voice working in other apps or with the screen off (uses more battery)'
            }
            value={settings.backgroundListening}
            onValueChange={(v) => updateSettings({ backgroundListening: v })}
          />
          <View style={styles.padded}>
            <Text style={[caption, { color: theme.textDim }]}>
              Speech rate: {settings.speechRate.toFixed(2)}×
            </Text>
            <Stepper
              value={Math.round(settings.speechRate * 100)}
              min={50}
              max={200}
              step={10}
              name="speech rate"
              formatValue={(v) => `${(v / 100).toFixed(2)}×`}
              theme={theme}
              onChange={(v) => updateSettings({ speechRate: v / 100 })}
            />
          </View>
        </Card>

        <SectionTitle>About you</SectionTitle>
        <Card>
          <Text style={[caption, { color: theme.textDim, marginBottom: 12 }]}>
            This shapes how AdaptiveAI talks and acts. It is stored only on this phone.
          </Text>
          <TextField
            label="Your name"
            value={profile.displayName}
            onChangeText={(v) => updateProfile({ displayName: v })}
            placeholder="Optional"
          />
          <Text style={[caption, { color: theme.textDim, marginBottom: 8 }]}>Accessibility need</Text>
          <Chips
            options={NEEDS.map((n) => n.value)}
            labels={Object.fromEntries(NEEDS.map((n) => [n.value, n.label]))}
            value={profile.accessibilityNeed}
            theme={theme}
            u={u}
            onChange={(v) => updateProfile({ accessibilityNeed: v as AccessibilityNeed })}
          />
          <Text style={[caption, { color: theme.textDim, marginTop: 16, marginBottom: 8 }]}>
            How much detail
          </Text>
          <Chips
            options={['terse', 'normal', 'detailed']}
            value={profile.verbosity}
            theme={theme}
            u={u}
            onChange={(v) => updateProfile({ verbosity: v as never })}
          />
          <Text style={[caption, { color: theme.textDim, marginTop: 16, marginBottom: 8 }]}>
            Word choice
          </Text>
          <Chips
            options={['simple', 'standard', 'technical']}
            value={profile.languageComplexity}
            theme={theme}
            u={u}
            onChange={(v) => updateProfile({ languageComplexity: v as never })}
          />
          <View style={styles.padded}>
            <Text style={[caption, { color: theme.textDim }]}>
              Interface size: {profile.uiScale.toFixed(2)}×
            </Text>
            <Stepper
              value={Math.round(profile.uiScale * 100)}
              min={85}
              max={160}
              step={5}
              name="interface size"
              formatValue={(v) => `${(v / 100).toFixed(2)}×`}
              theme={theme}
              onChange={(v) => updateProfile({ uiScale: v / 100 })}
            />
          </View>
          <View style={styles.flush}>
            <Toggle
              label="High contrast"
              value={profile.highContrast}
              onValueChange={(v) => updateProfile({ highContrast: v })}
            />
          </View>
        </Card>

        <SectionTitle>Saved details for form filling</SectionTitle>
        <Card>
          <Text style={[caption, { color: theme.textDim, marginBottom: 12 }]}>
            AdaptiveAI uses these to fill forms for you without asking again. Stored on the device
            only.
          </Text>
          {(
            [
              ['fullName', 'Full name'],
              ['email', 'Email'],
              ['phone', 'Phone'],
              ['address', 'Address'],
              ['city', 'City'],
              ['postcode', 'Postcode'],
              ['country', 'Country'],
              ['dateOfBirth', 'Date of birth'],
            ] as const
          ).map(([field, label]) => (
            <TextField
              key={field}
              label={label}
              value={profile.savedFields[field]}
              onChangeText={(v) => updateSavedFields({ [field]: v } as never)}
              keyboardType={field === 'email' ? 'email-address' : field === 'phone' ? 'phone-pad' : 'default'}
              autoCapitalize={field === 'email' ? 'none' : field === 'fullName' || field === 'city' || field === 'country' ? 'words' : 'sentences'}
            />
          ))}
        </Card>

        <SectionTitle>Teach AdaptiveAI</SectionTitle>
        <Card>
          <Text style={[caption, { color: theme.textDim, marginBottom: 12 }]}>
            Standing instructions it will follow on every future task.
          </Text>
          <TextField
            label="New instruction"
            value={correctionNote}
            onChangeText={setCorrectionNote}
            placeholder="e.g. always use my Gmail address, never my work one"
            multiline
          />
          <Button label="Save instruction" onPress={addCorrection} disabled={!correctionNote.trim()} />
          {profile.corrections.length ? (
            <View style={styles.correctionList}>
              {profile.corrections.map((c) => (
                <View key={c.id} style={[styles.correctionRow, { borderColor: theme.border }]}>
                  <Text style={[caption, { color: theme.text, flex: 1 }]}>{c.note}</Text>
                </View>
              ))}
            </View>
          ) : null}
        </Card>

        <Text style={[caption, { color: theme.textDim, textAlign: 'center', marginTop: 26 }]}>
          AdaptiveAI · no backend · model calls go straight to Google Gemini Flash
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

function maskKey(key: string): string {
  if (!key) return '';
  if (key.length <= 12) return '•'.repeat(key.length);
  return `${key.slice(0, 9)}${'•'.repeat(8)}${key.slice(-4)}`;
}

function Chips({
  options,
  labels,
  value,
  onChange,
  theme,
  u,
}: {
  options: string[];
  labels?: Record<string, string>;
  value: string;
  onChange: (next: string) => void;
  theme: ReturnType<typeof useTheme>;
  u: number;
}) {
  return (
    <View style={styles.chips}>
      {options.map((opt) => {
        const active = opt === value;
        return (
          <Pressable
            key={opt}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            accessibilityLabel={labels?.[opt] ?? opt}
            onPress={() => onChange(opt)}
            style={[
              styles.chip,
              {
                backgroundColor: active ? theme.accent : theme.surfaceAlt,
                borderColor: active ? theme.accent : theme.border,
                borderRadius: theme.radius,
              },
            ]}
          >
            <Text
              numberOfLines={1}
              style={[
                { fontSize: scaled(12, u) },
                { color: active ? theme.accentText : theme.textDim },
              ]}
            >
              {labels?.[opt] ?? opt}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function Stepper({
  value,
  min,
  max,
  step = 1,
  name,
  formatValue,
  onChange,
  theme,
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  name: string;
  formatValue?: (v: number) => string;
  onChange: (next: number) => void;
  theme: ReturnType<typeof useTheme>;
}) {
  const clamp = (n: number) => Math.min(max, Math.max(min, n));
  const displayed = formatValue ? formatValue(value) : String(value);
  return (
    <View style={styles.stepper}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Decrease ${name}`}
        onPress={() => onChange(clamp(value - step))}
        style={[styles.stepButton, { backgroundColor: theme.surfaceAlt, borderColor: theme.border }]}
      >
        <Text style={[styles.stepGlyph, { color: theme.text }]}>−</Text>
      </Pressable>
      <Text style={[styles.stepValue, { color: theme.text }]} accessibilityLabel={displayed}>
        {displayed}
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Increase ${name}`}
        onPress={() => onChange(clamp(value + step))}
        style={[styles.stepButton, { backgroundColor: theme.surfaceAlt, borderColor: theme.border }]}
      >
        <Text style={[styles.stepGlyph, { color: theme.text }]}>+</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: 16, paddingBottom: 60 },
  flush: { paddingHorizontal: 0, paddingVertical: 0 },
  padded: { paddingHorizontal: 16, paddingVertical: 12 },
  buttonRow: { flexDirection: 'row', gap: 10, marginTop: 6 },
  grow: { flex: 1 },
  resultBox: { borderWidth: 1, borderRadius: 10, padding: 11, marginTop: 12 },
  linkRow: { marginTop: 12 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    borderWidth: 1,
    paddingHorizontal: 12,
    paddingVertical: 8,
    minHeight: 48,
    maxWidth: '100%',
    justifyContent: 'center',
  },
  stepper: { flexDirection: 'row', alignItems: 'center', gap: 14, marginTop: 10 },
  stepButton: {
    width: 48,
    height: 48,
    borderRadius: 12,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepGlyph: { fontSize: 22, fontWeight: '600', lineHeight: 26 },
  stepValue: { fontSize: 16, fontWeight: '700', minWidth: 44, textAlign: 'center' },
  correctionList: { marginTop: 14, gap: 8 },
  correctionRow: { borderWidth: 1, borderRadius: 10, padding: 11, flexDirection: 'row' },
});
