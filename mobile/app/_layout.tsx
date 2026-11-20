import { Stack } from 'expo-router';
import * as StatusBar from 'expo-status-bar';
import React from 'react';
import type { ReactNode } from 'react';
import { Pressable, Text, View, useColorScheme } from 'react-native';

import { AppProviders, useTheme } from '../src/ui/AppProviders';

function ErrorFallback({ message, onRetry }: { message?: string; onRetry: () => void }) {
  return (
    <View
      style={{
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        backgroundColor: '#0B0F14',
      }}
    >
      <View style={{ maxWidth: 420, width: '100%' }}>
        <Text style={{ color: '#F2F6FA', fontSize: 18, fontWeight: '700' }}>
          Something went wrong
        </Text>
        <Text style={{ color: '#9AA7B4', fontSize: 13, lineHeight: 19, marginTop: 8 }}>
          {message ? `Error: ${message}. ` : ''}
          Please force-close and reopen AdaptiveAI. Your settings and notes are saved on this phone.
        </Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Try again"
          onPress={onRetry}
          style={{
            marginTop: 16,
            backgroundColor: '#76B900',
            borderRadius: 12,
            minHeight: 48,
            alignItems: 'center',
            justifyContent: 'center',
            paddingHorizontal: 16,
          }}
        >
          <Text style={{ color: '#08110A', fontWeight: '700' }}>Try again</Text>
        </Pressable>
        <Text style={{ color: '#9AA7B4', fontSize: 12, marginTop: 12, lineHeight: 17 }}>
          If “Try again” does not help, swipe the app away from Recents and reopen it.
        </Text>
      </View>
    </View>
  );
}

/**
 * Inner boundary for render errors inside the provider tree. Uses getDerivedStateFromError
 * the normal React way, so it works regardless of how it is mounted.
 */
class RootErrorBoundary extends React.Component<
  { children: ReactNode },
  { hasError: boolean; message?: string }
> {
  state = { hasError: false, message: undefined as string | undefined };

  static getDerivedStateFromError(err: Error) {
    return { hasError: true, message: err?.message };
  }

  render() {
    if (this.state.hasError) {
      return (
        <ErrorFallback
          message={this.state.message}
          onRetry={() => this.setState({ hasError: false, message: undefined })}
        />
      );
    }
    return this.props.children;
  }
}

/**
 * expo-router's contract for a route-level `ErrorBoundary` export: it is rendered as
 * `<ErrorBoundary error={error} retry={retry} />` with NO children. Exporting a class
 * boundary here meant `render()` returned `undefined` whenever it actually fired — a
 * permanently blank screen with nothing for TalkBack to announce.
 */
export function ErrorBoundary({ error, retry }: { error?: Error; retry?: () => void }) {
  return (
    <ErrorFallback
      message={error?.message}
      onRetry={() => {
        if (retry) retry();
      }}
    />
  );
}

function RootStack() {
  const theme = useTheme();
  const scheme = useColorScheme();
  return (
    <>
      <StatusBar.StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: theme.bg },
          animation: 'fade',
        }}
      >
        <Stack.Screen name="(tabs)" />
      </Stack>
    </>
  );
}

export default function RootLayout() {
  // The boundary must sit OUTSIDE the providers: if AppProviders itself throws during
  // render, an inner boundary never sees it and expo-router's own fallback takes over.
  // The fallback uses hard-coded colours, so it needs no theme from those providers.
  return (
    <RootErrorBoundary>
      <AppProviders>
        <RootStack />
      </AppProviders>
    </RootErrorBoundary>
  );
}
