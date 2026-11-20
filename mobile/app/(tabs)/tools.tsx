import { Ionicons } from '@expo/vector-icons';
import { Audio } from 'expo-av';
import * as ImagePicker from 'expo-image-picker';
import { useLocalSearchParams, useRouter } from 'expo-router';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import * as FileSystem from 'expo-file-system';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { assist, assistAvailable } from '../../src/native/assist';
import { engineChat } from '../../src/services/engine';
import {
  addCareContact,
  removeCareContact,
  composeSosMessage,
  describeSos,
  sendSos,
} from '../../src/services/careCircle';
import {
  deleteEmergencyNote,
  loadEmergencyNotes,
  saveEmergencyNote,
} from '../../src/services/emergencyNotes';
import type { EmergencyNote } from '../../src/services/emergencyNotes';
import { useGeminiApiKey, useProfile, useSettings } from '../../src/services/profile';
import { useTheme } from '../../src/ui/AppProviders';
import { alertFeedback, Button, Card, Header, SectionTitle, TextField } from '../../src/ui/components';
import { scaled, SPACE } from '../../src/theme';

export default function ToolsTab() {
  const theme = useTheme();
  const router = useRouter();
  const params = useLocalSearchParams<{ record?: string }>();
  const profile = useProfile();
  const settings = useSettings();
  const geminiApiKey = useGeminiApiKey();
  const u = profile.uiScale;

  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState('');
  const [recording, setRecording] = useState<Audio.Recording | null>(null);
  const [recordMs, setRecordMs] = useState(0);
  const [notes, setNotes] = useState<EmergencyNote[]>([]);
  const [playing, setPlaying] = useState<string | null>(null);
  const soundRef = useRef<Audio.Sound | null>(null);
  const recordingRef = useRef<Audio.Recording | null>(null);
  const recordTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Guards against a double tap starting two recordings / two playbacks while awaits are in flight.
  const startingRef = useRef(false);
  const scanningRef = useRef(false);
  const playTokenRef = useRef(0);

  // Contact form state.
  const [contactName, setContactName] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  const [sosBusy, setSosBusy] = useState(false);

  const speak = useCallback(
    (text: string) => {
      if (!settings.speakResponses || !assistAvailable) return;
      void assist.speak(text, settings.speechRate, settings.language).catch(() => {});
    },
    [settings.speakResponses, settings.speechRate, settings.language],
  );

  const stopPlayback = useCallback(async () => {
    // Invalidate any playNote whose createAsync is still in flight so its sound is dropped.
    playTokenRef.current += 1;
    await soundRef.current?.stopAsync().catch(() => {});
    await soundRef.current?.unloadAsync().catch(() => {});
    soundRef.current = null;
    setPlaying(null);
  }, []);

  useEffect(() => {
    void loadEmergencyNotes().then(setNotes).catch(() => {});
    return () => {
      // Tear down BOTH the player and any in-progress recording — previously a recording
      // kept running (and its file leaked) if the user left the tab mid-record.
      void soundRef.current?.unloadAsync().catch(() => {});
      soundRef.current = null;
      const live = recordingRef.current;
      recordingRef.current = null;
      void live
        ?.stopAndUnloadAsync()
        .catch(() => {});
      if (recordTimerRef.current) clearInterval(recordTimerRef.current);
      // Leave the audio session usable for playback (speaker, not the earpiece receiver).
      void Audio.setAudioModeAsync({ allowsRecordingIOS: false, playsInSilentModeIOS: true }).catch(() => {});
    };
  }, []);

  const scanProduct = useCallback(
    async (rescan = false) => {
      if (scanningRef.current) return;
      scanningRef.current = true;
      setScanning(true);
      // Everything after setScanning(true) MUST live inside this try/finally: a rejected
      // permission request (ColorOS interrupts the dialog) used to escape before the
      // finally, leaving scanningRef stuck true and the Scan button dead forever.
      try {
        if (!geminiApiKey) {
          Alert.alert('Gemini key needed', 'Add your free Gemini key in Settings first (aistudio.google.com).');
          speak('Gemini key needed. Add your free Gemini key in Settings first.');
          return;
        }
        const permission = await ImagePicker.requestCameraPermissionsAsync();
        if (!permission?.granted) {
          Alert.alert('Camera blocked', 'Allow camera access to identify a product.', [
            { text: 'Cancel', style: 'cancel' },
            { text: 'Open app settings', onPress: () => assist.openAppSettings().catch(() => {}) },
          ]);
          speak('Camera blocked. Allow camera access to identify a product.');
          return;
        }
        if (!rescan) setScanResult('');
        const result = await ImagePicker.launchCameraAsync({
          base64: true,
          // Lower quality keeps a 48 MP photo's base64 payload from OOMing
          // the vision call (SDK 51 removed maxWidth from the picker options).
          quality: 0.5,
          exif: false,
        });
        if (result.canceled || !result.assets?.[0]?.base64) return;
        speak('Looking at the product.');
        const response = await engineChat({
          geminiApiKey,
          settings,
          imageBase64: result.assets[0].base64,
          messages: [
            {
              role: 'system',
              content:
                'You identify products for a blind or low-vision user. Be honest about uncertainty. Never invent text.',
            },
            {
              role: 'user',
              content:
                'Identify the visible product. Report, in this order: brand and product name, size or weight, ' +
                'price if visible, expiry or best-before date, and any warnings. Say "not visible" when unknown. ' +
                'Keep it under 100 words and speakable — no bullet points, no markdown.',
            },
          ],
        });
        setScanResult(response.text);
        speak(response.text);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        Alert.alert('Product scan failed', message);
        speak(`Product scan failed. ${message}`);
      } finally {
        scanningRef.current = false;
        setScanning(false);
      }
    },
    [geminiApiKey, settings, speak],
  );

  const startRecording = useCallback(async () => {
    // Double tap (or the deep-link effect racing a tap) used to start two recordings and leak
    // the first one's mic + file — refuse while a start is already in flight or one is live.
    if (startingRef.current || recordingRef.current) return;
    startingRef.current = true;
    try {
      const permission = await Audio.requestPermissionsAsync();
      if (!permission.granted) {
        Alert.alert('Microphone blocked', 'Allow microphone access to record an emergency note.', [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Open app settings', onPress: () => assist.openAppSettings().catch(() => {}) },
        ]);
        return;
      }
      await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });
      const result = await Audio.Recording.createAsync(Audio.RecordingOptionsPresets.HIGH_QUALITY);
      recordingRef.current = result.recording;
      setRecording(result.recording);
      setRecordMs(0);
      recordTimerRef.current = setInterval(() => setRecordMs((ms) => ms + 100), 100);
    } catch (err) {
      Alert.alert('Recording failed', `The microphone could not be started: ${err instanceof Error ? err.message : String(err)}`);
      void Audio.setAudioModeAsync({ allowsRecordingIOS: false, playsInSilentModeIOS: true }).catch(() => {});
    } finally {
      startingRef.current = false;
    }
  }, []);

  const stopRecording = useCallback(async () => {
    const started = recordingRef.current;
    if (!started) return;
    recordingRef.current = null;
    setRecording(null);
    if (recordTimerRef.current) {
      clearInterval(recordTimerRef.current);
      recordTimerRef.current = null;
    }
    try {
      await started.stopAndUnloadAsync();
    } catch {
      Alert.alert('Recording failed', 'The audio file could not be saved.');
      return;
    } finally {
      // Take the iOS session out of record mode, or later note playback routes to the
      // earpiece receiver instead of the speaker.
      void Audio.setAudioModeAsync({ allowsRecordingIOS: false, playsInSilentModeIOS: true }).catch(() => {});
    }
    const recordedUri = started.getURI();
    if (!recordedUri) {
      Alert.alert('Recording failed', 'The audio file was not created.');
      return;
    }
    // expo-av records into the OS cache by default — Android purges cache files,
    // which left persisted notes pointing at nothing. Copy into documentDirectory
    // (never purged) BEFORE persisting.
    let uri = recordedUri;
    try {
      const dir = (FileSystem.documentDirectory ?? recordedUri) + 'notes/';
      await FileSystem.makeDirectoryAsync(dir, { intermediates: true });
      const dest = dir + `note-${Date.now()}.m4a`;
      await FileSystem.copyAsync({ from: recordedUri, to: dest });
      uri = dest;
    } catch {
      // Keep the original URI rather than losing the note; playback may still work.
    }
    const durationMs = recordMs;
    const note: EmergencyNote = { id: `note-${Date.now()}`, uri, at: Date.now(), durationMs };
    try {
      await saveEmergencyNote(note);
      setNotes((current) => [note, ...current].slice(0, 50));
      speak('Emergency voice note saved on this phone.');
    } catch (err) {
      Alert.alert('Could not save note', `The note was recorded but could not be saved: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [recordMs, speak]);

  const playNote = useCallback(
    async (note: EmergencyNote) => {
      await stopPlayback();
      const token = ++playTokenRef.current;
      try {
        const { sound } = await Audio.Sound.createAsync({ uri: note.uri });
        if (token !== playTokenRef.current) {
          // A newer Play tap or a Stop won while we were loading — drop this sound untouched
          // instead of orphaning it (it would keep playing with no handle to stop it).
          void sound.unloadAsync().catch(() => {});
          return;
        }
        soundRef.current = sound;
        setPlaying(note.id);
        sound.setOnPlaybackStatusUpdate((status) => {
          if ('didJustFinish' in status && status.didJustFinish) {
            setPlaying(null);
            void sound.unloadAsync().catch(() => {});
            soundRef.current = null;
          }
        });
        await sound.playAsync();
      } catch {
        if (token !== playTokenRef.current) return;
        // The recording file may have been cleaned up by the OS cache — surface it honestly
        // and drop the dead entry.
        setPlaying(null);
        Alert.alert('Cannot play', 'The audio file is gone (the system may have cleared its cache). Deleting the entry.');
        await deleteEmergencyNote(note.id).catch(() => {});
        setNotes((current) => current.filter((item) => item.id !== note.id));
      }
    },
    [stopPlayback],
  );

  const removeNote = useCallback(async (note: EmergencyNote) => {
    try {
      if (playing === note.id) await stopPlayback();
      await deleteEmergencyNote(note.id);
      setNotes((current) => current.filter((item) => item.id !== note.id));
      speak('Note deleted.');
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      Alert.alert('Could not delete', message);
      speak(`Could not delete the note. ${message}`);
    }
  }, [playing, stopPlayback, speak]);

  // Deep link from the Assistant voice shortcut ("record an emergency note").
  useEffect(() => {
    if (params.record === '1') {
      const shouldRecord = !recording && !sosBusy;
      router.setParams({ record: undefined });
      if (shouldRecord) void startRecording().catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.record]);

  const runSos = useCallback(async () => {
    alertFeedback();
    const contacts = profile.careContacts ?? [];
    if (contacts.length === 0) {
      Alert.alert('No care contacts', 'Add a trusted contact below first.');
      return;
    }
    setSosBusy(true);
    try {
      const approved = await new Promise<boolean>((resolve) => {
        Alert.alert(
          'Confirm SOS',
          describeSos(contacts),
          [
            { text: "Don't send", style: 'cancel', onPress: () => resolve(false) },
            { text: 'Send', onPress: () => resolve(true) },
          ],
          // Android back/outside dismissal fires no button onPress — resolve false there too,
          // or sosBusy stays true and the emergency button is stuck on "Working…".
          { cancelable: true, onDismiss: () => resolve(false) },
        );
      });
      if (!approved) {
        speak('Emergency message cancelled.');
        return;
      }
      const message = await composeSosMessage({
        senderName: profile.displayName,
        note: notes[0] ? `A voice note was recorded at ${new Date(notes[0].at).toLocaleString()}.` : null,
        includeLocation: true,
      });
      const opened = await sendSos(message, contacts);
      speak(
        opened > 0
          ? `Emergency message ready for ${contacts.length} contact${contacts.length > 1 ? 's' : ''}. Press send in the messaging app.`
          : 'No messaging app was available.',
      );
    } finally {
      setSosBusy(false);
    }
  }, [notes, profile.careContacts, profile.displayName, speak]);

  const onAddContact = useCallback(async () => {
    const ok = await addCareContact(contactName, contactPhone);
    if (!ok) return;
    setContactName('');
    setContactPhone('');
    speak('Contact saved on this phone.');
  }, [contactName, contactPhone, speak]);

  const contacts = profile.careContacts ?? [];
  const fmtMs = (ms?: number) =>
    ms ? `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, '0')}` : '';

  return (
    <SafeAreaView style={[styles.flex, { backgroundColor: theme.bg }]} edges={['top']}>
      <Header title="Tools" subtitle="Private tools that stay on this phone" />
      <ScrollView contentContainerStyle={styles.content}>
        <SectionTitle>PRODUCT IDENTIFICATION</SectionTitle>
        <Card icon="camera" title="Scan a product" label="Product identification">
          <Text style={{ color: theme.textDim, fontSize: scaled(13, u), lineHeight: scaled(19, u), marginTop: SPACE.xs }}>
            Take a photo and hear the name, brand, size, price, expiry, and warnings — spoken back.
          </Text>
          <Button
            label={scanResult ? 'Scan another product' : 'Scan product with camera'}
            icon="camera"
            onPress={() => void scanProduct(Boolean(scanResult)).catch(() => {})}
            busy={scanning}
            style={styles.button}
          />
          {scanResult ? (
            <Text
              accessibilityLiveRegion="polite"
              style={{ color: theme.text, fontSize: scaled(14, u), lineHeight: scaled(20, u), marginTop: SPACE.sm }}
            >
              {scanResult}
            </Text>
          ) : null}
        </Card>

        <SectionTitle>CARE CIRCLE — EMERGENCY</SectionTitle>
        <Card icon="people" title="Care circle" label="Care circle contacts, stored on this phone only">
          <Text style={{ color: theme.textDim, fontSize: scaled(13, u), lineHeight: scaled(19, u) }}>
            Trusted people who get your emergency message. Contacts live in this app only — nothing
            is uploaded.
          </Text>
          {contacts.map((c) => (
            <View key={c.id} style={[styles.contactRow, { borderTopColor: theme.border }]}>
              <Ionicons name="person-circle" size={22} color={theme.textDim} />
              <View style={styles.flex1}>
                <Text style={{ color: theme.text, fontSize: scaled(14, u), fontWeight: '600' }}>{c.name}</Text>
                <Text style={{ color: theme.textDim, fontSize: scaled(12, u) }}>{c.phone}</Text>
              </View>
              <Button
                label="Remove"
                accessibilityLabel={`Remove contact ${c.name}`}
                variant="ghost"
                onPress={() => void removeCareContact(c.id)}
              />
            </View>
          ))}
          {contacts.length < 6 ? (
            <View style={{ marginTop: SPACE.sm }}>
              <TextField
                label="Contact name"
                value={contactName}
                onChangeText={setContactName}
                placeholder="e.g. Mom"
              />
              <TextField
                label="Phone number"
                value={contactPhone}
                onChangeText={setContactPhone}
                placeholder="+91…"
                keyboardType="phone-pad"
                autoCapitalize="none"
              />
              <Button
                label="Add contact"
                icon="person-add"
                variant="secondary"
                onPress={() => void onAddContact()}
                disabled={!contactName.trim() || contactPhone.replace(/[^\d+]/g, '').length < 5}
              />
            </View>
          ) : null}
        </Card>

        <Card tone="danger" icon="warning" title="Send emergency message" label="Emergency SOS">
          <Text style={{ color: theme.textDim, fontSize: scaled(13, u), lineHeight: scaled(19, u) }}>
            Opens your messaging app with a pre-filled emergency text and your live location link
            for every care contact. You press send — nothing goes out silently.
          </Text>
          <Button
            label={sosBusy ? 'Working…' : 'Send emergency message'}
            icon="alert"
            variant="danger"
            onPress={() => runSos().catch((e) => {
              const message = e instanceof Error ? e.message : String(e);
              Alert.alert('Emergency send failed', message);
              speak(`The emergency message failed to send. ${message}`);
            })}
            disabled={sosBusy}
            style={styles.button}
          />
        </Card>

        <SectionTitle>EMERGENCY VOICE NOTES</SectionTitle>
        <Card icon="mic" title="Emergency voice notes" label="Emergency voice notes saved locally">
          <Text style={{ color: theme.textDim, fontSize: scaled(13, u), lineHeight: scaled(19, u) }}>
            Notes stay in this app on this phone. They are not uploaded automatically.
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={recording ? 'Stop and save emergency voice note' : 'Start emergency voice note'}
            accessibilityState={{ busy: Boolean(recording) }}
            onPress={recording ? () => void stopRecording() : () => void startRecording()}
            style={[
              styles.record,
              {
                backgroundColor: recording ? theme.danger : theme.accent,
                borderRadius: theme.radius,
                opacity: recording ? 1 : 0.96,
              },
            ]}
          >
            <Ionicons name={recording ? 'stop' : 'mic'} size={26} color={recording ? theme.onDanger : theme.accentText} />
            <Text style={{ color: recording ? theme.onDanger : theme.accentText, fontWeight: '700', fontSize: scaled(15, u) }}>
              {recording ? `Recording… ${fmtMs(recordMs)} — tap to save` : 'Record emergency note'}
            </Text>
          </Pressable>
          {notes.map((note) => (
            <View key={note.id} style={[styles.note, { borderTopColor: theme.border }]}>
              <View style={styles.flex1}>
                <Text style={{ color: theme.text, fontSize: scaled(13, u) }}>
                  {new Date(note.at).toLocaleString()}
                  {note.durationMs ? ` · ${fmtMs(note.durationMs)}` : ''}
                </Text>
              </View>
              <Button
                label={playing === note.id ? 'Stop' : 'Play'}
                accessibilityLabel={`${playing === note.id ? 'Stop playing' : 'Play'} note from ${new Date(note.at).toLocaleString()}`}
                icon={playing === note.id ? 'stop' : 'play'}
                variant="secondary"
                onPress={() => void (playing === note.id ? stopPlayback() : playNote(note))}
              />
              <Button
                label="Delete"
                accessibilityLabel={`Delete note from ${new Date(note.at).toLocaleString()}`}
                onPress={() => void removeNote(note).catch(() => {})}
                variant="ghost"
              />
            </View>
          ))}
        </Card>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: 16, paddingBottom: 40 },
  button: { marginTop: SPACE.md },
  record: {
    minHeight: 56,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    marginTop: SPACE.md,
    paddingHorizontal: 16,
  },
  note: { flexDirection: 'row', alignItems: 'center', gap: 8, borderTopWidth: 1, paddingTop: 10, marginTop: 10 },
  contactRow: { flexDirection: 'row', alignItems: 'center', gap: 10, borderTopWidth: 1, paddingTop: 10, marginTop: 10 },
  flex1: { flex: 1 },
});
