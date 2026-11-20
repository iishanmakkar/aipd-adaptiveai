import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import React, { useRef, useState } from 'react';
import { ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useProfile } from '../../src/services/profile';
import { useTheme } from '../../src/ui/AppProviders';
import { Button, Card, Chip, Header, SectionTitle } from '../../src/ui/components';
import { useSpeak } from '../../src/ui/useSpeak';
import { scaled, SPACE } from '../../src/theme';

const TASKS = [
  {
    icon: 'bus-outline' as const,
    title: 'Book a bus',
    detail: 'Open RedBus, search the route, and fill the booking details.',
    task: 'Open RedBus and help me search and book a bus. Ask me before payment, OTP, CAPTCHA, or any final purchase.',
  },
  {
    icon: 'cart-outline' as const,
    title: 'Order groceries',
    detail: 'Use Zepto or Blinkit to find groceries and fill the order.',
    task: 'Open Zepto or Blinkit and help me order the groceries I describe. Ask me to choose the app if both are installed. Ask me before payment, OTP, CAPTCHA, or final purchase.',
  },
  {
    icon: 'scan-outline' as const,
    title: 'Identify a product',
    detail: 'Use the camera and describe the product aloud.',
    task: 'Open the camera or use the current screen to identify the product in front of me. Describe its name, visible brand, size, expiry or price if readable, and uncertainty. Do not purchase anything.',
  },
  {
    icon: 'medkit-outline' as const,
    title: 'Order medicine',
    detail: 'Pharmacy apps, prescription details read aloud to you.',
    task: 'Open a pharmacy app like PharmEasy or 1mg and help me order the medicine I describe. Ask me before payment, OTP, CAPTCHA, or final purchase.',
  },
  {
    icon: 'train-outline' as const,
    title: 'Book a train',
    detail: 'Search trains, pick a class, fill passenger details.',
    task: 'Open a train booking app and help me search and book a train. Use my saved details for the form. Ask me before payment, OTP, CAPTCHA, or any final purchase.',
  },
];

const CHIPS = [
  'Order 1kg apples and milk',
  'Recharge my phone',
  'Find headphones under 2000 rupees',
  'Book a bus to Jaipur tomorrow',
];

export default function ShoppingTab() {
  const theme = useTheme();
  const profile = useProfile();
  const router = useRouter();
  const u = profile.uiScale;
  const [draft, setDraft] = useState('');
  const launchingRef = useRef(false);
  const speak = useSpeak();

  const launch = (task: string) => {
    const text = task.trim();
    if (!text) {
      speak('Type or say what you want to buy first.');
      return;
    }
    if (launchingRef.current) return;
    launchingRef.current = true;
    setDraft('');
    // Tell the user what is about to happen before the screen changes — a blind
    // user gets no other signal that the Assistant tab took over.
    speak(`Starting: ${text.length > 120 ? `${text.slice(0, 117)}...` : text}`);
    // nonce: re-tapping the same chip must re-run the task — params.task alone
    // is unchanged by a repeat push, so the Assistant effect would not re-fire.
    try {
      router.push({ pathname: '/', params: { task: text, nonce: `${Date.now()}-${Math.random()}` } });
    } catch (err) {
      // A throw here used to skip the timeout below, locking the whole tab forever.
      console.warn('[shopping] navigation failed:', err);
      speak('That task could not be opened. Try again.');
    } finally {
      setTimeout(() => { launchingRef.current = false; }, 1200);
    }
  };

  const frequent = profile.frequentTasks ?? [];

  return (
    <SafeAreaView style={[styles.flex, { backgroundColor: theme.bg }]} edges={['top']}>
      <Header
        title="Shopping"
        subtitle="Voice-first shopping help for blind and low-vision users"
      />
      <ScrollView contentContainerStyle={styles.content}>
        <Card label="Shopping assistant introduction" tone="accent" icon="sparkles">
          <Text style={{ color: theme.text, fontSize: scaled(16, u), fontWeight: '700' }}>
            Tell AdaptiveAI what you need
          </Text>
          <Text style={{ color: theme.textDim, fontSize: scaled(13, u), lineHeight: scaled(19, u), marginTop: 8 }}>
            Type or dictate a goal below, or pick a card. AdaptiveAI plans the steps, drives the app
            for you, and stops before payment, OTP, CAPTCHA, or the final purchase.
          </Text>
          <View style={{ marginTop: SPACE.md, gap: SPACE.sm }}>
            <TextInput
              value={draft}
              onChangeText={setDraft}
              placeholder="e.g. order 1kg apples and milk from Zepto"
              placeholderTextColor={theme.textDim}
              accessibilityLabel="Shopping goal"
              multiline
              // Multiline defaults to blurOnSubmit=false, which kills onSubmitEditing on iOS
              // and inserts a newline on Android; blur first so the "go" key actually launches.
              blurOnSubmit
              onSubmitEditing={() => launch(draft)}
              returnKeyType="go"
              style={[
                styles.input,
                {
                  backgroundColor: theme.surfaceAlt,
                  borderColor: theme.border,
                  borderRadius: theme.radius,
                  color: theme.text,
                  fontSize: scaled(15, u),
                },
              ]}
            />
            <Button label="Do it" icon="arrow-forward" onPress={() => launch(draft)} disabled={!draft.trim()} />
          </View>
          <View style={styles.chipRow}>
            {CHIPS.map((c) => (
              <Chip key={c} label={c} onPress={() => launch(c)} />
            ))}
          </View>
        </Card>

        {frequent.length > 0 ? (
          <>
            <SectionTitle>DO IT AGAIN</SectionTitle>
            <View style={styles.chipRow}>
              {frequent.slice(0, 6).map((t) => (
                <Chip
                  key={t.phrase}
                  label={`${t.phrase.length > 30 ? `${t.phrase.slice(0, 29)}…` : t.phrase} (${t.count})`}
                  icon="repeat"
                  onPress={() => launch(t.phrase)}
                />
              ))}
            </View>
          </>
        ) : null}

        <SectionTitle>SHOPPING TASKS</SectionTitle>
        {TASKS.map((item) => (
          <Card
            key={item.title}
            icon={item.icon}
            title={item.title}
            description={item.detail}
            onPress={() => launch(item.task)}
            style={styles.taskCard}
          />
        ))}

        <SectionTitle>SAFETY</SectionTitle>
        <Card label="Shopping safety information" icon="shield-checkmark">
          <Text style={{ color: theme.textDim, fontSize: scaled(13, u), lineHeight: scaled(19, u) }}>
            AdaptiveAI never guesses a payment, OTP, PIN, CAPTCHA, or password. It reads the
            checkout total aloud and waits for your spoken decision.
          </Text>
        </Card>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: 16, paddingBottom: 40 },
  input: {
    minHeight: 64,
    borderWidth: 1,
    paddingHorizontal: 14,
    paddingVertical: 12,
    textAlignVertical: 'top',
  },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm, marginTop: SPACE.md },
  taskCard: { marginBottom: SPACE.xs },
});
