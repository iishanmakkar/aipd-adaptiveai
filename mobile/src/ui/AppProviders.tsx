import React, { createContext, useContext, useEffect, useMemo } from 'react';
import { useColorScheme } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { loadAll, useProfile } from '../services/profile';
import { pickTheme } from '../theme';
import type { Theme } from '../theme';

const ThemeContext = createContext<Theme>(pickTheme(true, false));

export function useTheme(): Theme {
  return useContext(ThemeContext);
}

export function AppProviders({ children }: { children: React.ReactNode }) {
  const scheme = useColorScheme();
  const profile = useProfile();

  useEffect(() => {
    console.log('[boot] AppProviders mounted, loading stored state');
    loadAll()
      .then(() => console.log('[boot] stored state loaded'))
      .catch((err) => console.log('[boot] loadAll failed:', String(err && err.message)));
  }, []);

  const theme = useMemo(
    () => pickTheme(scheme !== 'light', profile.highContrast),
    [scheme, profile.highContrast],
  );

  // Render immediately with defaults and hydrate in the background: gating the first frame on
  // Keystore/AsyncStorage reads produced a permanent black screen when either read stalled.
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
