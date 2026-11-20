import * as Location from 'expo-location';
import { Alert, AppState, Linking, Platform, Share } from 'react-native';

import { getSnapshot, updateProfile } from './profile';

export type CareContact = {
  id: string;
  name: string;
  phone: string;
};

function sanitizeContacts(raw: unknown): CareContact[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter(
      (c): c is CareContact =>
        Boolean(c) &&
        typeof c === 'object' &&
        typeof (c as CareContact).id === 'string' &&
        typeof (c as CareContact).name === 'string' &&
        typeof (c as CareContact).phone === 'string' &&
        (c as CareContact).phone.replace(/[^\d+]/g, '').length >= 5,
    )
    .slice(0, 6);
}

export async function saveCareContacts(contacts: CareContact[]): Promise<void> {
  await updateProfile({ careContacts: sanitizeContacts(contacts) });
}

export function normalizePhone(phone: string): string {
  const trimmed = phone.trim();
  const digits = trimmed.replace(/[^\d]/g, '');
  return trimmed.startsWith('+') ? `+${digits}` : digits;
}

export async function addCareContact(name: string, phone: string): Promise<boolean> {
  const trimmedName = name.trim();
  const normalized = normalizePhone(phone);
  const digitsOnly = normalized.replace(/\D/g, '');
  if (!trimmedName || digitsOnly.length < 5 || digitsOnly.length > 15) {
    Alert.alert('Contact incomplete', 'A name and a valid phone number (5–15 digits) are required.');
    return false;
  }
  const current = sanitizeContacts(getSnapshot().profile.careContacts);
  await saveCareContacts([
    // Date.now() alone collides for two saves in the same millisecond, and removeCareContact
    // deletes by id — a collision would delete both contacts at once.
    { id: `cc-${Date.now()}-${Math.floor(Math.random() * 1e6)}`, name: trimmedName, phone: normalized },
    ...current,
  ]);
  return true;
}

export async function removeCareContact(id: string): Promise<void> {
  const current = sanitizeContacts(getSnapshot().profile.careContacts);
  await saveCareContacts(current.filter((c) => c.id !== id));
}

/**
 * One-shot location permission + coordinates. Returns null when the user declines —
 * the SOS message is still sent, just without a map link.
 */
export async function getCurrentLocation(): Promise<{ lat: number; lon: number } | null> {
  // One hard deadline over the WHOLE body, not just the GPS fix. The permission dialog
  // (first SOS on Realme), hasServicesEnabledAsync() and getLastKnownPositionAsync() were
  // each unbounded, so an unanswered dialog stalled the emergency message at
  // "Preparing the emergency message" indefinitely. Emergency beats location: when the
  // deadline hits we send the SOS without a map link.
  let timer: ReturnType<typeof setTimeout> | null = null;
  try {
    const result = await Promise.race([
      resolveLocation().catch(() => null),
      new Promise<null>((resolve) => {
        timer = setTimeout(() => resolve(null), 7000);
      }),
    ]);
    return result;
  } catch {
    return null;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function resolveLocation(): Promise<{ lat: number; lon: number } | null> {
  const perm = await Location.requestForegroundPermissionsAsync();
  if (!perm.granted) return null;
  if (!(await Location.hasServicesEnabledAsync())) return null;
  // Last-known first (instant), then High accuracy with a 5s cap.
  try {
    const last = await Location.getLastKnownPositionAsync({ maxAge: 60000 });
    if (last) return { lat: last.coords.latitude, lon: last.coords.longitude };
  } catch {}
  let gpsTimer: ReturnType<typeof setTimeout> | null = null;
  try {
    const pos = await Promise.race([
      Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High }).catch(() => null),
      new Promise<null>((resolve) => {
        gpsTimer = setTimeout(() => resolve(null), 5000);
      }),
    ]);
    if (!pos) return null;
    return { lat: pos.coords.latitude, lon: pos.coords.longitude };
  } finally {
    if (gpsTimer) clearTimeout(gpsTimer);
  }
}

export type SosPayload = {
  senderName: string;
  note?: string | null;
  includeLocation: boolean;
};

/** Compose the human-readable SOS text. A map link is appended when location is available. */
export async function composeSosMessage(payload: SosPayload): Promise<string> {
  const who = payload.senderName.trim() || 'An AdaptiveAI user';
  const parts: string[] = [`EMERGENCY — ${who} needs help.`];
  if (payload.note) parts.push(`Voice note: ${payload.note}`);
  if (payload.includeLocation) {
    const loc = await getCurrentLocation();
    if (loc) {
      parts.push(`My location: https://maps.google.com/?q=${loc.lat.toFixed(5)},${loc.lon.toFixed(5)}`);
    } else {
      parts.push('Location unavailable.');
    }
  }
  parts.push('(Sent automatically by the AdaptiveAI app on their phone.)');
  return parts.join('\n');
}

/**
 * Opens the SMS app for each care contact with the message pre-filled. Nothing is sent
 * silently — the user confirms on each compose screen. Returns how many compose screens
 * were opened.
 *
 * Honest limitation (built into Android/iOS): the `?body=` parameter is ignored by many
 * messenger apps, so the user MUST still press Send and must check the message is there.
 * When no SMS compose opens, the system Share sheet carries the full text instead.
 */
export async function sendSos(message: string, contacts: CareContact[]): Promise<number> {
  let opened = 0;
  const encoded = encodeURIComponent(message).replace(/%0A/g, ' ');
  for (let i = 0; i < contacts.length; i++) {
    const digits = normalizePhone(contacts[i].phone);
    const url = Platform.OS === 'ios' ? `sms:${digits}&body=${encoded}` : `sms:${digits}?body=${encoded}`;
    let thisOpened = false;
    try {
      await Linking.openURL(url);
      thisOpened = true;
      opened += 1;
    } catch {
      // No SMS handler for this URL (or the scheme is not declared) — do NOT open a bare
      // `sms:` link, which would present an empty compose screen and silently drop the
      // emergency message. The share sheet below carries the full text instead.
    }
    // Opening the next compose screen immediately clobbers the one in front of the user —
    // wait until they come back to the app first (bounded, so a stuck listener cannot hang
    // the SOS flow forever).
    if (thisOpened && i < contacts.length - 1) {
      try { await waitForAppReturn(60000); } catch {}
    }
  }
  if (opened === 0) {
    // Last resort that works everywhere: the system share sheet (carries the full text,
    // unlike the sms: body parameter which many OEM apps silently drop).
    await Share.share({ message }).catch(() => {});
  }
  return opened;
}

/** Resolves when the app returns to the foreground, or after timeoutMs as a safety valve. */
function waitForAppReturn(timeoutMs: number): Promise<void> {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      sub.remove();
      clearTimeout(timer);
      resolve();
    };
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') finish();
    });
    const timer = setTimeout(finish, timeoutMs);
  });
}

/** Announce-ready spoken summary of what SOS just did, for the confirm dialog and TTS. */
export function describeSos(contacts: CareContact[]): string {
  if (contacts.length === 0) {
    return 'No care contacts are saved yet. Add one in Tools first.';
  }
  const names = contacts.map((c) => c.name).join(', ');
  return contacts.length === 1
    ? `Send an emergency message with your location to ${names}?`
    : `Send an emergency message with your location to ${contacts.length} contacts: ${names}?`;
}
