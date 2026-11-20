import React, { useCallback } from 'react';
import { Alert, FlatList, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useProfile, useTasks } from '../../src/services/profile';
import type { TaskRecord } from '../../src/services/profile';
import { clearTasks } from '../../src/services/profile';
import { useTheme } from '../../src/ui/AppProviders';
import { Button, Header, Pill } from '../../src/ui/components';
import { useSpeak } from '../../src/ui/useSpeak';
import { scaled } from '../../src/theme';

function whenText(at: number): string {
  const diff = Date.now() - at;
  const mins = Math.round(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(at).toLocaleDateString();
}

export default function TasksTab() {
  const theme = useTheme();
  const profile = useProfile();
  const tasks = useTasks();
  const speak = useSpeak();
  const u = profile.uiScale;

  const confirmClear = useCallback(() => {
    if (!tasks.length) {
      speak('There are no tasks to clear yet.');
      return;
    }
    speak(`Clear ${tasks.length} stored task${tasks.length === 1 ? '' : 's'}? Confirm in the dialog.`);
    Alert.alert('Clear history?', 'This removes the task log from this device.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Clear',
        style: 'destructive',
        onPress: () => {
          clearTasks();
          speak('Task history cleared.');
        },
      },
    ]);
  }, [tasks.length, speak]);

  const toneFor = (status: TaskRecord['status']) =>
    status === 'completed'
      ? 'ok'
      : status === 'running'
        ? 'warn'
        : status === 'awaiting_input'
          ? 'warn'
          : status === 'cancelled'
            ? 'neutral'
            : 'danger';

  return (
    <SafeAreaView style={[styles.flex, { backgroundColor: theme.bg }]} edges={['top']}>
      <Header
        title="Tasks"
        subtitle={tasks.length ? `${tasks.length} stored on this device` : 'Nothing run yet'}
        right={
          tasks.length ? (
            <Button label="Clear" variant="ghost" onPress={confirmClear} style={styles.clearButton} />
          ) : undefined
        }
      />

      <FlatList
        style={styles.flex}
        contentContainerStyle={styles.content}
        data={tasks}
        keyExtractor={(item) => item.id}
        ListEmptyComponent={
          <View style={styles.centered}>
            <Text style={[{ fontSize: scaled(15, u), color: theme.textDim, textAlign: 'center' }]}>
              Tasks you run appear here with how many steps they took and what happened. The log
              never leaves the phone.
            </Text>
          </View>
        }
        renderItem={({ item }) => (
          <View
            accessible
            accessibilityRole="summary"
            accessibilityLabel={`${item.instruction}, ${item.status}. ${item.summary}. ${whenText(item.at)}, ${item.steps} step${item.steps === 1 ? '' : 's'}${item.app ? `, ${item.app}` : ''}.`}
            style={[
              styles.row,
              { backgroundColor: theme.surface, borderColor: theme.border, borderRadius: theme.radius },
            ]}
          >
            <View style={styles.rowHead}>
              <Text
                numberOfLines={2}
                style={[{ fontSize: scaled(15, u), color: theme.text, fontWeight: '600', flex: 1 }]}
              >
                {item.instruction}
              </Text>
              <Pill text={item.status.toUpperCase()} tone={toneFor(item.status) as never} />
            </View>
            <Text style={[{ fontSize: scaled(13, u), color: theme.textDim, marginTop: 6 }]}>
              {item.summary}
            </Text>
            <Text style={[{ fontSize: scaled(11, u), color: theme.textDim, marginTop: 8 }]}>
              {whenText(item.at)} · {item.steps} step{item.steps === 1 ? '' : 's'}
              {item.app ? ` · ${item.app}` : ''}
            </Text>
          </View>
        )}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: 16, paddingBottom: 40 },
  centered: { alignItems: 'center', justifyContent: 'center', padding: 34 },
  clearButton: { minHeight: 48, paddingHorizontal: 14 },
  row: { borderWidth: 1, padding: 15, marginBottom: 10 },
  rowHead: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
});
