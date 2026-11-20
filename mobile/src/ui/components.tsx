import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleProp,
  StyleSheet,
  Text,
  TextInput,
  TextStyle,
  View,
  ViewStyle,
} from 'react-native';

import { useProfile } from '../services/profile';
import { elevation, scaled, SPACE } from '../theme';
import { useTheme } from './AppProviders';

/** Light impact tap feedback for the actions a blind user must be able to feel. */
export function tapFeedback() {
  Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
}

/** Heavier pulse for record/SOS moments. */
export function alertFeedback() {
  Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
}

export function Header({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}) {
  const theme = useTheme();
  const s = useSizes();
  return (
    <View style={[styles.header, { borderBottomColor: theme.border }]}>
      <View style={styles.headerText}>
        <Text accessibilityRole="header" style={[s.title, { color: theme.text }]}>
          {title}
        </Text>
        {subtitle ? <Text style={[s.subtitle, { color: theme.textDim }]}>{subtitle}</Text> : null}
      </View>
      {right}
    </View>
  );
}

export function Card({
  children,
  style,
  label,
  icon,
  title,
  description,
  onPress,
  tone = 'surface',
}: {
  children?: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  label?: string;
  icon?: keyof typeof Ionicons.glyphMap;
  title?: string;
  description?: string;
  onPress?: () => void;
  tone?: 'surface' | 'accent' | 'danger';
}) {
  const theme = useTheme();
  const s = useSizes();

  const toneBg =
    tone === 'accent' ? theme.accentSoft : tone === 'danger' ? theme.dangerSoft : theme.surface;
  const toneBorder =
    tone === 'accent' ? theme.accent : tone === 'danger' ? theme.danger : theme.border;
  const toneIcon = tone === 'danger' ? theme.danger : tone === 'accent' ? theme.accent : theme.textDim;

  const body = (
    <>
      {icon || title ? (
        <View style={styles.cardHead}>
          {icon ? (
            <View style={[styles.cardIcon, { backgroundColor: tone === 'surface' ? theme.surfaceAlt : 'transparent' }]}>
              <Ionicons name={icon} size={scaled(22, s.u)} color={toneIcon} />
            </View>
          ) : null}
          <View style={styles.cardHeadText}>
            {title ? (
              <Text style={[s.headline, { color: theme.text }]}>{title}</Text>
            ) : null}
            {description ? (
              <Text style={[s.caption, { color: theme.textDim, marginTop: 3 }]}>{description}</Text>
            ) : null}
          </View>
        </View>
      ) : null}
      {children}
    </>
  );

  const cardStyle = [
    styles.card,
    {
      backgroundColor: toneBg,
      borderColor: toneBorder,
      borderRadius: theme.radius,
    },
    elevation,
    style,
  ];

  if (!onPress) {
    return (
      <View accessible accessibilityLabel={label} style={cardStyle}>
        {body}
      </View>
    );
  }
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label ?? (title ? `${title}${description ? `. ${description}` : ''}` : undefined)}
      onPress={() => {
        tapFeedback();
        onPress();
      }}
      style={({ pressed }) => [...cardStyle, pressed && styles.pressed]}
    >
      {body}
    </Pressable>
  );
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  const theme = useTheme();
  const s = useSizes();
  return <Text style={[s.section, { color: theme.textDim }]}>{children}</Text>;
}

export function Button({
  label,
  accessibilityLabel,
  onPress,
  variant = 'primary',
  icon,
  disabled,
  busy,
  style,
  labelStyle,
}: {
  label: string;
  /** Overrides the visible label for screen readers (e.g. to name which row a button acts on). */
  accessibilityLabel?: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  icon?: keyof typeof Ionicons.glyphMap;
  disabled?: boolean;
  busy?: boolean;
  style?: StyleProp<ViewStyle>;
  labelStyle?: StyleProp<TextStyle>;
}) {
  const theme = useTheme();
  const s = useSizes();

  const bg =
    variant === 'primary'
      ? theme.accent
      : variant === 'danger'
        ? theme.danger
        : variant === 'secondary'
          ? theme.surfaceAlt
          : 'transparent';
  const fg =
    variant === 'primary'
      ? theme.accentText
      : variant === 'danger'
        ? theme.onDanger
        : theme.text;
  const borderColor = variant === 'ghost' ? theme.border : bg;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled: Boolean(disabled || busy), busy: Boolean(busy) }}
      disabled={disabled || busy}
      onPress={() => {
        tapFeedback();
        onPress();
      }}
      style={({ pressed }) => [
        styles.button,
        {
          backgroundColor: bg,
          borderColor,
          borderRadius: theme.radius,
          opacity: (disabled || busy) ? 0.45 : pressed ? 0.8 : 1,
        },
        style,
      ]}
    >
      {busy ? (
        <ActivityIndicator color={fg} size="small" />
      ) : (
        <View style={styles.buttonContent}>
          {icon ? <Ionicons name={icon} size={scaled(17, s.u)} color={fg} /> : null}
          <Text style={[s.buttonLabel, { color: fg }, labelStyle]}>{label}</Text>
        </View>
      )}
    </Pressable>
  );
}

export function Pill({
  text,
  tone = 'neutral',
}: {
  text: string;
  tone?: 'neutral' | 'ok' | 'warn' | 'danger';
}) {
  const theme = useTheme();
  const s = useSizes();
  const color =
    tone === 'ok' ? theme.ok : tone === 'warn' ? theme.warn : tone === 'danger' ? theme.danger : theme.textDim;
  return (
    <View
      style={[styles.pill, { borderColor: color, backgroundColor: tone === 'neutral' ? 'transparent' : color === theme.ok ? theme.okSoft : color === theme.warn ? theme.warnSoft : theme.dangerSoft, borderRadius: theme.radius }]}
    >
      <Text style={[s.pill, { color }]}>{text}</Text>
    </View>
  );
}

/** Small tappable suggestion chip — used by the Shopping composer and Assistant examples. */
export function Chip({
  label,
  icon,
  onPress,
  selected,
  accessibilityLabel,
}: {
  label: string;
  icon?: keyof typeof Ionicons.glyphMap;
  onPress: () => void;
  selected?: boolean;
  /** Full spoken label when the visible label is truncated. */
  accessibilityLabel?: string;
}) {
  const theme = useTheme();
  const s = useSizes();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ selected: Boolean(selected) }}
      onPress={() => {
        tapFeedback();
        onPress();
      }}
      style={({ pressed }) => [
        styles.chip,
        {
          backgroundColor: selected ? theme.accent : theme.surfaceAlt,
          borderColor: selected ? theme.accent : theme.border,
          borderRadius: theme.radius,
          opacity: pressed ? 0.8 : 1,
        },
      ]}
    >
      {icon ? <Ionicons name={icon} size={scaled(15, s.u)} color={selected ? theme.accentText : theme.textDim} /> : null}
      <Text style={[s.chip, { color: selected ? theme.accentText : theme.text }]}>{label}</Text>
    </Pressable>
  );
}

/** Thin horizontal progress bar for multi-step agent runs. */
export function ProgressBar({ ratio, tone }: { ratio: number; tone?: 'accent' | 'danger' }) {
  const theme = useTheme();
  return (
    <View
      accessible
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max: 100, now: Math.round(ratio * 100) }}
      accessibilityLabel={`Progress ${Math.round(ratio * 100)} percent`}
      style={[styles.progressTrack, { backgroundColor: theme.surfaceAlt }]}
    >
      <View
        style={[
          styles.progressFill,
          {
            backgroundColor: tone === 'danger' ? theme.danger : theme.accent,
            width: `${Math.min(100, Math.max(0, Math.round(ratio * 100)))}%`,
          },
        ]}
      />
    </View>
  );
}

export function Row({
  label,
  value,
  onPress,
  right,
  icon,
}: {
  label: string;
  value?: string;
  onPress?: () => void;
  right?: React.ReactNode;
  icon?: keyof typeof Ionicons.glyphMap;
}) {
  const theme = useTheme();
  const s = useSizes();
  const content = (
    <>
      {icon ? (
        <View style={styles.rowIcon}>
          <Ionicons name={icon} size={scaled(18, s.u)} color={theme.textDim} />
        </View>
      ) : null}
      <View style={styles.rowText}>
        <Text style={[s.body, { color: theme.text }]}>{label}</Text>
        {value ? <Text style={[s.caption, { color: theme.textDim }]}>{value}</Text> : null}
      </View>
      {right ?? (onPress ? <Ionicons name="chevron-forward" size={scaled(18, s.u)} color={theme.textDim} /> : null)}
    </>
  );

  if (!onPress) {
    return <View style={[styles.row, { borderBottomColor: theme.border }]}>{content}</View>;
  }
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${label}${value ? `, ${value}` : ''}`}
      onPress={() => {
        tapFeedback();
        onPress();
      }}
      style={({ pressed }) => [
        styles.row,
        { borderBottomColor: theme.border, opacity: pressed ? 0.7 : 1 },
      ]}
    >
      {content}
    </Pressable>
  );
}

export function Toggle({
  label,
  description,
  value,
  onValueChange,
}: {
  label: string;
  value: boolean;
  description?: string;
  onValueChange: (next: boolean) => void;
}) {
  const theme = useTheme();
  const s = useSizes();
  return (
    <Pressable
      accessibilityRole="switch"
      accessibilityLabel={description ? `${label}. ${description}` : label}
      accessibilityState={{ checked: value }}
      onPress={() => {
        tapFeedback();
        onValueChange(!value);
      }}
      style={({ pressed }) => [styles.row, { borderBottomColor: theme.border, opacity: pressed ? 0.7 : 1 }]}
    >
      <View style={styles.rowText}>
        <Text style={[s.body, { color: theme.text }]}>{label}</Text>
        {description ? <Text style={[s.caption, { color: theme.textDim }]}>{description}</Text> : null}
      </View>
      <View
        style={[
          styles.switchTrack,
          { backgroundColor: value ? theme.accent : theme.surfaceAlt, borderColor: theme.border },
        ]}
      >
        <View
          style={[
            styles.switchThumb,
            { backgroundColor: value ? theme.accentText : theme.textDim, alignSelf: value ? 'flex-end' : 'flex-start' },
          ]}
        />
      </View>
    </Pressable>
  );
}

export function TextField({
  label,
  value,
  onChangeText,
  placeholder,
  secure,
  keyboardType,
  autoCapitalize = 'sentences',
  multiline,
}: {
  label: string;
  value: string;
  onChangeText: (next: string) => void;
  placeholder?: string;
  secure?: boolean;
  keyboardType?: 'default' | 'email-address' | 'numeric' | 'phone-pad' | 'url';
  autoCapitalize?: 'none' | 'sentences' | 'words' | 'characters';
  multiline?: boolean;
}) {
  const theme = useTheme();
  const s = useSizes();
  return (
    <View style={styles.field}>
      <Text style={[s.caption, { color: theme.textDim }]}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={theme.textDim}
        secureTextEntry={secure}
        keyboardType={keyboardType}
        autoCapitalize={autoCapitalize}
        autoCorrect={false}
        multiline={multiline}
        accessibilityLabel={label}
        style={[
          styles.input,
          {
            backgroundColor: theme.surfaceAlt,
            borderColor: theme.border,
            borderRadius: theme.radius,
            color: theme.text,
            fontSize: s.body.fontSize,
            minHeight: multiline ? 84 : undefined,
            textAlignVertical: multiline ? 'top' : 'center',
          },
        ]}
      />
    </View>
  );
}

function useSizes() {
  const profile = useProfile();
  const u = profile.uiScale;
  return { u, ...StyleSheet.create({
    title: { fontSize: scaled(26, u), fontWeight: '700', letterSpacing: -0.4 },
    subtitle: { fontSize: scaled(13, u), marginTop: 3 },
    section: {
      fontSize: scaled(11, u),
      fontWeight: '700',
      letterSpacing: 1.1,
      textTransform: 'uppercase',
      marginTop: 22,
      marginBottom: 8,
    },
    body: { fontSize: scaled(15, u), lineHeight: scaled(21, u) },
    caption: { fontSize: scaled(12, u), lineHeight: scaled(17, u) },
    headline: { fontSize: scaled(17, u), fontWeight: '700', lineHeight: scaled(23, u) },
    buttonLabel: { fontSize: scaled(15, u), fontWeight: '700' },
    pill: { fontSize: scaled(11, u), fontWeight: '700' },
    chip: { fontSize: scaled(13, u), fontWeight: '600' },
  }) };
}

const styles = StyleSheet.create({
  header: {
    paddingHorizontal: SPACE.lg,
    paddingTop: 56,
    paddingBottom: SPACE.md,
    borderBottomWidth: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerText: { flex: 1, paddingRight: 12 },
  card: { padding: SPACE.md + 2, borderWidth: 1, marginHorizontal: SPACE.md + 2, marginVertical: SPACE.sm + 2 },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, marginBottom: SPACE.sm + 2 },
  cardHeadText: { flex: 1 },
  cardIcon: {
    width: 44,
    height: 44,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pressed: { opacity: 0.82, transform: [{ scale: 0.99 }] },
  button: {
    minHeight: 52,
    paddingHorizontal: SPACE.md + 4,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
  },
  buttonContent: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  pill: { borderWidth: 1, paddingHorizontal: 9, paddingVertical: 3 },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderWidth: 1,
    paddingHorizontal: SPACE.md,
    minHeight: 48,
  },
  progressTrack: { height: 6, borderRadius: 3, overflow: 'hidden' },
  progressFill: { height: '100%', borderRadius: 3 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: SPACE.md + 2,
    paddingVertical: SPACE.md,
    borderBottomWidth: 1,
    minHeight: 56,
  },
  rowIcon: { marginRight: SPACE.md },
  rowText: { flex: 1, paddingRight: 12 },
  switchTrack: {
    width: 52,
    height: 32,
    borderRadius: 16,
    borderWidth: 1,
    padding: 2,
    justifyContent: 'center',
  },
  switchThumb: { width: 26, height: 26, borderRadius: 13 },
  field: { marginBottom: SPACE.md },
  input: { borderWidth: 1, paddingHorizontal: 13, paddingVertical: 11, minHeight: 48 },
});
