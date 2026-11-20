import { Ionicons } from '@expo/vector-icons';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AccessibilityInfo,
  ActivityIndicator,
  Alert,
  FlatList,
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { assist, assistAvailable, ensureNotificationPermission } from '../../src/native/assist';
import type { ScreenNode, ScreenTree } from '../../src/native/assist';
import { useProfile, useSettings } from '../../src/services/profile';
import { useTheme } from '../../src/ui/AppProviders';
import { Button, Card, Header, Pill, TextField } from '../../src/ui/components';
import { scaled } from '../../src/theme';

// A monospace stack that exists on Android without shipping extra font assets.
const MONO = 'monospace';

export default function ScreenTab() {
  const theme = useTheme();
  const profile = useProfile();
  const settings = useSettings();
  const u = profile.uiScale;

  const [tree, setTree] = useState<ScreenTree | null>(null);
  const [busy, setBusy] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<ScreenNode | null>(null);
  const [fillValue, setFillValue] = useState('');
  const [shot, setShot] = useState<string | null>(null);
  const [shotBusy, setShotBusy] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  // Track the media-projection session separately from the preview image: dismissing the
  // preview must not orphan a live capture session (virtual display + status-bar notification).
  const [capturing, setCapturing] = useState(false);
  const capturingRef = useRef(false);
  const [ocrText, setOcrText] = useState('');
  const [detects, setDetects] = useState<{ label: string; score: number; cx: number; cy: number }[]>([]);
  const [shareBusy, setShareBusy] = useState(false);
  const [workBusy, setWorkBusy] = useState(false);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // The error Card is the only feedback a failed action gives; make sure screen readers hear it.
  useEffect(() => {
    if (error) AccessibilityInfo.announceForAccessibility(error);
  }, [error]);

  const [rawLines, setRawLines] = useState(200);

  // Tabs stay mounted — stop the capture session when this screen unmounts or it
  // keeps the media-projection FGS + privacy indicator alive in the background.
  useEffect(() => {
    return () => {
      if (capturingRef.current) {
        void assist.stopScreenCapture().catch(() => {});
        capturingRef.current = false;
      }
    };
  }, []);

  /** Eyes-free feedback for failures on the main action paths — mirror readAloud's pattern. */
  const speakError = useCallback(
    (message: string) => {
      void assist.speak(message, settings.speechRate, settings.language).catch(() => {});
    },
    [settings.speechRate, settings.language],
  );

  const sizes = {
    body: { fontSize: scaled(14, u) },
    caption: { fontSize: scaled(12, u) },
    mono: { fontSize: scaled(11, u), fontFamily: MONO },
  };

  const refresh = useCallback(async () => {
    setBusy(true);
    setError('');
    try {
      const next = await assist.readScreen(500);
      setTree(next);
      setSelected(null);
      setFillValue('');
      return next;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      speakError(`Read screen failed. ${message}`);
      setTree(null);
      setSelected(null);
      setFillValue('');
      return null;
    } finally {
      setBusy(false);
    }
  }, [speakError]);

  /** Eyes-free path: read the screen and speak the visible controls, no model call needed. */
  const readAloud = useCallback(async () => {
    await assist.stopSpeaking().catch(() => {});
    setSpeaking(true);
    setError('');
    try {
      const next = await refresh(); // always fresh, never speak a stale tree as current
      if (!next) {
        void assist
          .speak('I could not read the screen. Is it on and unlocked?', settings.speechRate, settings.language)
          .catch(() => {});
        return;
      }
      const items = next.nodes
        .filter((n) => n.text || n.desc)
        .slice(0, 14)
        .map((n) => (n.text || n.desc || '').replace(/\s+/g, ' ').trim())
        .filter(Boolean);
      const spoken = items.length
        ? `On screen, ${items.length} items: ${items.join('. ')}.`
        : 'The screen has no readable text right now.';
      await assist.speak(spoken, settings.speechRate, settings.language).catch(() => {});
    } finally {
      setSpeaking(false);
    }
  }, [refresh, settings.language, settings.speechRate]);

  const takeShot = useCallback(async () => {
    setShotBusy(true);
    setError('');
    try {
      await ensureNotificationPermission();
      const st = await assist.getStatus();
      if (!st.captureActive) {
        // requestScreenCapture resolves to whether the user accepted the consent dialog;
        // a denial must stop here instead of surfacing an opaque capture_inactive error.
        const granted = await assist.requestScreenCapture();
        if (!granted) {
          setError('Screenshot: screen capture was not granted.');
          speakError('Screen capture was not granted.');
          return;
        }
      }
      const base64 = await assist.captureScreen(72);
      setShot(base64);
      capturingRef.current = true;
      setCapturing(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(`Screenshot: ${message}`);
      speakError(`Screenshot failed. ${message}`);
      setShot(null);
    } finally {
      setShotBusy(false);
    }
  }, [speakError]);

  const stopShot = useCallback(async () => {
    try {
      await assist.stopScreenCapture();
      setShot(null);
      capturingRef.current = false;
      setCapturing(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      speakError(`Stop capture failed. ${message}`);
      // Resync UI with native state instead of lying.
      try {
        const st = await assist.getStatus();
        capturingRef.current = st.captureActive;
        setCapturing(st.captureActive);
      } catch {}
    }
  }, [speakError]);

  const ensureCapture = useCallback(async (): Promise<boolean> => {
    const st = await assist.getStatus();
    if (!st.captureActive) {
      const ok = await ensureNotificationPermission();
      if (!ok) {
        setError('Notifications are off — Android needs them for screen capture. Allow notifications and try again.');
        speakError('Notifications are off. Allow notifications for screen capture.');
        return false;
      }
      const granted = await assist.requestScreenCapture();
      if (!granted) {
        setError('Screen capture was not granted.');
        speakError('Screen capture was not granted.');
        return false;
      }
    }
    if (!mountedRef.current) {
      void assist.stopScreenCapture().catch(() => {});
      return false;
    }
    capturingRef.current = true;
    setCapturing(true);
    return true;
  }, [speakError]);

  const shareShot = useCallback(async () => {
    setError('');
    setShareBusy(true);
    try {
      if (!(await ensureCapture())) return;
      await assist.shareScreen(90);
      capturingRef.current = true;
      setCapturing(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(`Share screen: ${message}`);
      speakError(`Share screen failed. ${message}`);
    } finally {
      setShareBusy(false);
    }
  }, [ensureCapture, speakError]);

  const runOcr = useCallback(async () => {
    if (workBusy) return;
    setWorkBusy(true);
    setError('');
    try {
      if (!(await ensureCapture())) return;
      const text = await assist.ocrScreen(72);
      if (!mountedRef.current) return;
      setOcrText(text);
      void assist.speak(text ? `I see text: ${text.slice(0, 300)}` : 'No text found in the screenshot.', settings.speechRate, settings.language).catch(() => {});
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (mountedRef.current) setError(`OCR: ${message}`);
      speakError(`OCR failed. ${message}`);
    } finally {
      setWorkBusy(false);
    }
  }, [ensureCapture, settings.language, settings.speechRate, speakError, workBusy]);

  const runDetect = useCallback(async () => {
    if (workBusy) return;
    setWorkBusy(true);
    setError('');
    try {
      if (!(await ensureCapture())) return;
      const list = await assist.detectObjects(72);
      if (!mountedRef.current) return;
      setDetects(list);
      const spoken = list.length
        ? `I see: ${list.slice(0, 6).map((d) => `${d.label} ${Math.round(d.score * 100)}%`).join(', ')}.`
        : 'I see no objects in the screenshot.';
      void assist.speak(spoken, settings.speechRate, settings.language).catch(() => {});
      AccessibilityInfo.announceForAccessibility(spoken);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (mountedRef.current) setError(`Detect: ${message}`);
      speakError(`Object detection failed. ${message}`);
    } finally {
      setWorkBusy(false);
    }
  }, [ensureCapture, settings.language, settings.speechRate, speakError, workBusy]);

  const act = useCallback(
    async (kind: 'click' | 'fill') => {
      if (!selected || workBusy) return;
      // Guard stale selection: id must still exist in the last tree the user saw.
      if (tree && !tree.nodes.some((n) => n.id === selected.id)) {
        const msg = 'That element is no longer on screen. Read the screen again.';
        setError(msg);
        speakError(msg);
        return;
      }
      setWorkBusy(true);
      try {
        if (kind === 'click') {
          const ok = await assist.clickNode(selected.id);
          const msg = ok ? `Clicked ${selected.id}.` : `Click on ${selected.id} had no effect.`;
          Alert.alert(ok ? 'Clicked' : 'Click had no effect', `Node ${selected.id}`);
          void assist.speak(msg, settings.speechRate, settings.language).catch(() => {});
          AccessibilityInfo.announceForAccessibility(msg);
        } else {
          const res = await assist.fillNode(selected.id, fillValue);
          if (!res || typeof res.ok !== 'boolean') throw new Error('Malformed fill result');
          const msg = res.ok ? `Filled. Field now reads "${res.text ?? ''}".` : 'Fill was rejected. That node does not accept text.';
          Alert.alert(
            res.ok ? 'Filled' : 'Fill rejected',
            res.ok ? `Field now reads "${res.text}"` : 'That node does not accept text.',
          );
          void assist.speak(msg, settings.speechRate, settings.language).catch(() => {});
          AccessibilityInfo.announceForAccessibility(msg);
        }
        await refresh();
      } catch (err) {
        const msg = `Action failed. ${err instanceof Error ? err.message : String(err)}`;
        Alert.alert('Action failed', err instanceof Error ? err.message : String(err));
        void assist.speak(msg, settings.speechRate, settings.language).catch(() => {});
        AccessibilityInfo.announceForAccessibility(msg);
      } finally {
        setWorkBusy(false);
      }
    },
    [fillValue, refresh, selected, settings.language, settings.speechRate, tree, workBusy],
  );

  const tapAt = useCallback(async () => {
    if (!selected || workBusy) return;
    setWorkBusy(true);
    try {
      const ok = await assist.tap(selected.cx, selected.cy);
      const msg = ok ? `Tapped ${selected.cx}, ${selected.cy}.` : `Tap at ${selected.cx}, ${selected.cy} was cancelled.`;
      Alert.alert(ok ? 'Tapped coordinates' : 'Tap cancelled', `${selected.cx}, ${selected.cy}`);
      void assist.speak(msg, settings.speechRate, settings.language).catch(() => {});
      AccessibilityInfo.announceForAccessibility(msg);
      await refresh();
    } catch (err) {
      const msg = `Tap failed. ${err instanceof Error ? err.message : String(err)}`;
      Alert.alert('Tap failed', err instanceof Error ? err.message : String(err));
      void assist.speak(msg, settings.speechRate, settings.language).catch(() => {});
      AccessibilityInfo.announceForAccessibility(msg);
    } finally {
      setWorkBusy(false);
    }
  }, [refresh, selected, settings.language, settings.speechRate, workBusy]);

  if (!assistAvailable) {
    return (
      <SafeAreaView style={[styles.flex, { backgroundColor: theme.bg }]} edges={['top']}>
        <Header title="Screen" />
        <Card style={styles.spaced}>
          <Text style={[sizes.body, { color: theme.text }]}>
            The native accessibility module is not present in this build.
          </Text>
        </Card>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={[styles.flex, { backgroundColor: theme.bg }]} edges={['top']}>
      <Header
        title="Screen"
        subtitle={
          tree
            ? `${tree.package} · ${tree.nodeCount} elements${tree.truncated ? ' · truncated' : ''}`
            : 'What AdaptiveAI can see right now'
        }
        right={busy ? <ActivityIndicator color={theme.accent} /> : undefined}
      />

      <View style={styles.actions}>
        <Button label="Read screen" onPress={refresh} busy={busy} style={styles.actionButton} />
        <Button
          label="Read aloud"
          variant="secondary"
          icon="volume-high"
          onPress={readAloud}
          busy={speaking}
          style={styles.actionButton}
        />
        <Button
          label="Screenshot"
          variant="secondary"
          onPress={takeShot}
          busy={shotBusy}
          disabled={shotBusy}
          style={styles.actionButton}
        />
        {capturing ? (
          <Button
            label="Stop capture"
            variant="danger"
            onPress={stopShot}
            style={styles.actionButton}
          />
        ) : null}
        <Button
          label={showRaw ? 'Readable' : 'Raw JSON'}
          variant="ghost"
          onPress={() => {
            setRawLines(200);
            setShowRaw((v) => !v);
          }}
          style={styles.actionButton}
        />
        <Button
          label="Share screen"
          variant="secondary"
          onPress={shareShot}
          busy={shareBusy}
          disabled={shareBusy}
          style={styles.actionButton}
        />
      </View>
      <View style={styles.actions}>
        <Button label="OCR text" variant="secondary" onPress={runOcr} busy={workBusy} disabled={workBusy} style={styles.actionButton} />
        <Button label="Detect objects" variant="secondary" onPress={runDetect} busy={workBusy} disabled={workBusy} style={styles.actionButton} />
      </View>
      {ocrText ? (
        <Card style={{ marginHorizontal: 16, marginBottom: 8 }}>
          <Text style={[sizes.caption, { color: theme.textDim }]}>OCR (on-device)</Text>
          <Text style={[sizes.body, { color: theme.text, marginTop: 6 }]}>{ocrText}</Text>
        </Card>
      ) : (
        <Text style={[sizes.caption, { color: theme.textDim, paddingHorizontal: 16 }]}>OCR: no text found in the last capture.</Text>
      )}
      {detects.length ? (
        <Card style={{ marginHorizontal: 16, marginBottom: 8 }}>
          <Text style={[sizes.caption, { color: theme.textDim }]}>Objects (MediaPipe, on-device)</Text>
          {detects.slice(0, 8).map((d, i) => (
            <Text key={i} style={[sizes.body, { color: theme.text, marginTop: 4 }]}>
              {d.label} — {Math.round(d.score * 100)}%
            </Text>
          ))}
        </Card>
      ) : null}

      {error ? (
        <Card style={{ borderColor: theme.danger }}>
          <Text style={[sizes.body, { color: theme.danger }]}>{error}</Text>
        </Card>
      ) : null}

      {shot ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Screenshot preview, double-tap to dismiss"
          onPress={() => setShot(null)}
        >
          <Image
            source={{ uri: `data:image/jpeg;base64,${shot}` }}
            style={[styles.shot, { borderColor: theme.border }]}
            resizeMode="contain"
            accessibilityLabel="Captured screen"
          />
        </Pressable>
      ) : null}

      {selected ? (
        <Card style={{ borderColor: theme.accent }}>
          <View style={styles.selectedHead}>
            <Text style={[sizes.body, { color: theme.text, fontWeight: '700', flex: 1 }]}>
              #{selected.id} {selected.cls}
            </Text>
            <Pill text={`${selected.cx},${selected.cy}`} />
          </View>
          <Text style={[sizes.caption, { color: theme.textDim, marginTop: 6 }]} numberOfLines={3}>
            {selected.text || selected.desc || selected.res || '(no label)'}
          </Text>
          <View style={styles.flagRow}>
            {selected.editable ? <Pill text="EDITABLE" tone="ok" /> : null}
            {selected.click ? <Pill text="CLICKABLE" tone="ok" /> : null}
            {selected.scroll ? <Pill text="SCROLLABLE" /> : null}
            {selected.password ? <Pill text="PASSWORD" tone="danger" /> : null}
            {selected.disabled ? <Pill text="DISABLED" tone="warn" /> : null}
          </View>
          <View style={styles.selectedActions}>
            <Button label="Click" onPress={() => act('click')} style={styles.actionButton} />
            <Button
              label="Tap coords"
              variant="secondary"
              onPress={tapAt}
              style={styles.actionButton}
            />
          </View>
          {selected.editable ? (
            <View style={styles.fillRow}>
              <View style={styles.flex}>
                <TextField
                  label="Text to type"
                  value={fillValue}
                  onChangeText={setFillValue}
                  placeholder="value"
                />
              </View>
              <Button
                label="Fill"
                onPress={() => act('fill')}
                disabled={!fillValue}
                style={styles.fillButton}
              />
            </View>
          ) : null}
        </Card>
      ) : null}

      {showRaw && tree ? (
        <RawJsonView tree={tree} rawLines={rawLines} onMore={() => setRawLines((n) => n + 200)} />
      ) : (
      <FlatList
        style={styles.flex}
        contentContainerStyle={styles.listContent}
        data={tree?.nodes ?? []}
        keyExtractor={(item: any, index) => String(item.id ?? index)}
        ListEmptyComponent={
          !busy ? (
            <View style={styles.centered}>
              <Ionicons name="eye-outline" size={40} color={theme.textDim} />
              <Text style={[sizes.body, { color: theme.textDim, marginTop: 12, textAlign: 'center' }]}>
                Press “Read screen” to dump the accessibility tree of whatever app is in front.
              </Text>
            </View>
          ) : null
        }
        renderItem={({ item }: any) => (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={String(item.text || item.desc || item.res || item.cls)}
              onPress={() => setSelected(item as ScreenNode)}
              style={({ pressed }) => [
                styles.nodeRow,
                {
                  borderBottomColor: theme.border,
                  backgroundColor:
                    selected?.id === item.id
                      ? theme.surfaceAlt
                      : pressed
                        ? theme.surfaceAlt
                        : 'transparent',
                },
              ]}
            >
              <Text style={[sizes.mono, { color: theme.accent, width: 40 }]}>#{item.id}</Text>
              <View style={styles.flex}>
                <Text style={[sizes.body, { color: theme.text }]} numberOfLines={1}>
                  {item.text || item.desc || <Text style={{ color: theme.textDim }}>{item.cls}</Text>}
                </Text>
                <Text style={[sizes.caption, { color: theme.textDim }]} numberOfLines={1}>
                  {item.cls}
                  {item.res ? ` · ${item.res.split('/').pop()}` : ''}
                </Text>
              </View>
              {item.editable ? <Pill text="EDIT" tone="ok" /> : null}
              {item.click ? <Pill text="TAP" /> : null}
            </Pressable>
          )
        }
      />
      )}
    </SafeAreaView>
  );
}

function RawJsonView({
  tree,
  rawLines,
  onMore,
}: {
  tree: ScreenTree;
  rawLines: number;
  onMore: () => void;
}) {
  const allLines = JSON.stringify(tree, null, 1).split('\n');
  const visible = allLines.slice(0, rawLines).join('\n');
  return (
    <View style={{ flex: 1 }}>
      <Text style={{ color: '#9AA7B4', paddingHorizontal: 16, fontSize: 11, fontFamily: MONO }} selectable>
        {visible}
      </Text>
      {rawLines < allLines.length ? (
        <Button label={`Show more (${rawLines}/${allLines.length} lines)`} variant="secondary" onPress={onMore} style={{ margin: 16 }} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  spaced: { marginTop: 16 },
  centered: { alignItems: 'center', justifyContent: 'center', padding: 30 },
  actions: { flexDirection: 'row', gap: 10, paddingHorizontal: 16, paddingVertical: 12 },
  actionButton: { flex: 1, minHeight: 48 },
  shot: { width: '100%', height: 240, borderWidth: 1, marginVertical: 6 },
  listContent: { paddingBottom: 30 },
  nodeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderBottomWidth: 1,
  },
  selectedHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  flagRow: { flexDirection: 'row', gap: 6, marginTop: 10, flexWrap: 'wrap' },
  selectedActions: { flexDirection: 'row', gap: 10, marginTop: 14 },
  fillRow: { flexDirection: 'row', alignItems: 'flex-end', gap: 10, marginTop: 14 },
  fillButton: { marginBottom: 14, minWidth: 80 },
});

