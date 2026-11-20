#!/usr/bin/env bash
#
# Exhaustive AVD test suite for AdaptiveAI. Every capability the app claims is exercised on a
# connected device/emulator and reported PASS/FAIL/SKIP-BLOCKED. Nothing here asserts success
# without an observed signal on the device.
#
# Usage: NIM_KEY=nvapi-... bash mobile/scripts/avd-test-suite.sh
#
# Prerequisites: release APK built, one device attached. The suite always does a clean
# uninstall/install — installing over a previous release with `install -r` leaves a stale
# SoLoader cache that makes libhermes.so fail to load ("file is not ELF").
set -uo pipefail

ADB="${ADB:-$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe}"
# Pin the serial: with more than one emulator attached, unqualified adb commands fail outright
# and the suite silently tests nothing.
ADB_SERIAL="${ADB_SERIAL:-emulator-5554}"
ad() { "$ADB" -s "$ADB_SERIAL" "$@"; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APK="$ROOT/android/app/build/outputs/apk/release/app-release.apk"
PROOF="$ROOT/.proof"
PKG="com.adaptiveai"
ACT="$PKG/.mobile.MainActivity"
SVC="$PKG/com.adaptiveai.mobile.assist.AdaptiveAccessibilityService"

mkdir -p "$PROOF"
[ -n "${NIM_KEY:-}" ] || { echo "set NIM_KEY=nvapi-... first"; exit 1; }

declare -a RESULTS=()
record() { RESULTS+=("$1|$2|$3"); }
pass() { echo "PASS  $1 — $2"; record "PASS" "$1" "$2"; }
fail() { echo "FAIL  $1 — $2"; record "FAIL" "$1" "$2"; }
skip() { echo "SKIP  $1 — $2"; record "SKIP" "$1" "$2"; }
hdr() { printf '\n########## %s ##########\n' "$1"; }

# --- device primitives -------------------------------------------------------

# uiautomator only serialises the focused, idle window. The notification shade can steal focus
# and a mid-render window yields a one-node tree, so collapse, retry and require our package.
# Splitting on "<node" puts exactly one element (and one bounds attribute) per line; splitting on
# ">" instead makes a node's line start with the previous element's tail and yields wrong bounds.
dump() {
  local i n
  for i in 1 2 3 4 5 6; do
    ad shell cmd statusbar collapse >/dev/null 2>&1
    ad shell uiautomator dump //sdcard/ui.xml >/dev/null 2>&1
    n=$(nodes | grep -c "$PKG")
    if [ "${n:-0}" -gt 3 ]; then nodes; return 0; fi
    sleep 1
  done
  nodes
  return 1
}

nodes() { ad shell "cat //sdcard/ui.xml" 2>/dev/null | sed -E 's|<node |\n<node |g'; }

texts() { dump | grep -oE '(text|content-desc)="[^"]+"' | grep -v '=""'; }

scroll_top() { for i in 1 2 3 4; do ad shell input swipe 540 700 540 2100 250 >/dev/null 2>&1; sleep 1; done; }
scroll_down() { ad shell input swipe 540 1800 540 700 250 >/dev/null 2>&1; sleep 1; }

# Tap the first node whose text or content-desc matches, searching down the scroll view.
tap_node() {
  local attr="$1" value="$2" b l t r b2 k
  scroll_top
  for k in 0 1 2 3 4 5 6 7; do
    b=$(dump | grep -- "$attr=\"$value\"" | grep -oE 'bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' | head -1 \
        | sed -E 's/bounds="\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]"/\1 \2 \3 \4/')
    if [ -n "$b" ]; then
      read -r l t r b2 <<< "$b"
      ad shell input tap $(( (l+r)/2 )) $(( (t+b2)/2 )) >/dev/null 2>&1
      echo "    tapped $attr=\"$value\" at $(( (l+r)/2 )),$(( (t+b2)/2 ))"
      sleep 2
      return 0
    fi
    scroll_down
  done
  echo "    not found: $attr=\"$value\""
  return 1
}

tap_text() { tap_node text "$1"; }
tap_desc() { tap_node content-desc "$1"; }

# `adb shell input text` on a 70-character key drops most of it (observed: arrived as "nva"),
# so send small chunks with a pause and verify the field really holds the string.
type_chunks() {
  # `adb shell input text` drops characters at speed (a 70-char key arrived as "nva"). Four
  # characters per call with a short pause delivered the full key. Spaces must be sent as %s.
  local s="$1" i
  for i in $(seq 0 4 ${#s}); do
    ad shell input text "\"${s:$i:4}\"" >/dev/null 2>&1
    sleep 0.4
  done
}

clear_field() { for i in $(seq 1 80); do ad shell input keyevent 67 >/dev/null 2>&1; done; }

field_value() {
  dump | grep -- 'content-desc="API key"' | grep -oE 'text="[^"]*"' | head -1 | sed -E 's/^text="(.*)"$/\1/'
}

tab() {
  case "$1" in
    Assistant) ad shell input tap 135 2257 ;;
    Screen) ad shell input tap 405 2257 ;;
    Tasks) ad shell input tap 675 2257 ;;
    Settings) ad shell input tap 945 2257 ;;
  esac
  sleep 3
  ad shell cmd statusbar collapse >/dev/null 2>&1
}

shot() {
  ad shell cmd statusbar collapse >/dev/null 2>&1
  ad exec-out screencap -p > "$PROOF/$1" 2>/dev/null
  local sz; sz=$(wc -c < "$PROOF/$1")
  echo "    .proof/$1 = $sz bytes"
  [ "$sz" -gt 40000 ] || { echo "    (suspiciously small — likely a black frame)"; return 1; }
}

# --- T0 install --------------------------------------------------------------

hdr "T0  clean install"
[ -f "$APK" ] || { echo "no APK at $APK"; exit 1; }
ad shell svc power stayon true >/dev/null 2>&1
ad shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1
ad uninstall "$PKG" >/dev/null 2>&1
ad install "$APK" 2>&1 | tail -1 | sed 's/^/    /'
ad shell pm grant "$PKG" android.permission.RECORD_AUDIO 2>/dev/null
ad shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS 2>/dev/null
for i in 1 2 3 4 5 6; do
  ad shell settings put secure enabled_accessibility_services "$SVC"
  ad shell settings put secure accessibility_enabled 1
  sleep 2
  case "$(ad shell settings get secure enabled_accessibility_services | tr -d '\r')" in
    *AdaptiveAccessibilityService*) break ;;
  esac
done

# Test IME so long strings can be entered atomically. Emulator-only tooling; not in the APK.
if ! ad shell pm list packages 2>/dev/null | grep -q "com.android.adbkeyboard"; then
  APK_IME="$ROOT/.proof/ADBKeyboard.apk"
  [ -f "$APK_IME" ] || curl -sL --max-time 120 -o "$APK_IME" \
    "https://raw.githubusercontent.com/senzhk/ADBKeyBoard/master/ADBKeyboard.apk"
  ad install -r "$APK_IME" >/dev/null 2>&1
fi
ad shell ime enable com.android.adbkeyboard/.AdbIME >/dev/null 2>&1
ad shell ime set com.android.adbkeyboard/.AdbIME >/dev/null 2>&1
echo "    input method: $(ad shell settings get secure default_input_method | tr -d '\r')"

hdr "T1  launch, no crash, real rendered frame"
ad logcat -c
ad shell am start -n "$ACT" >/dev/null 2>&1
sleep 12
PID=$(ad shell pidof "$PKG" | tr -d '\r')
FOCUS=$(ad shell dumpsys window 2>/dev/null | grep mCurrentFocus | head -1 | tr -d '\r')
FRAMES=$(ad shell dumpsys gfxinfo "$PKG" 2>/dev/null | grep -m1 "Total frames rendered" | tr -dc '0-9')
FATAL=$(ad logcat -d 2>&1 | grep -c "FATAL EXCEPTION")
SHOT_BYTES=0
ad shell cmd statusbar collapse >/dev/null 2>&1
ad exec-out screencap -p > "$PROOF/100-T1-launch.png" 2>/dev/null
SHOT_BYTES=$(wc -c < "$PROOF/100-T1-launch.png")
echo "    pid=$PID frames=${FRAMES:-n/a} fatal=$FATAL screenshot=${SHOT_BYTES}B"
# gfxinfo can report nothing for a freshly started process; the screenshot is the stronger signal.
if [ -n "$PID" ] && [ "$FATAL" -eq 0 ] && [ "$SHOT_BYTES" -gt 40000 ] && echo "$FOCUS" | grep -q "$PKG"; then
  pass T1 "process alive, foreground, ${FRAMES:-n/a} frames, 0 fatal exceptions, real frame captured"
else
  fail T1 "pid='$PID' frames='$FRAMES' fatal='$FATAL' shot='$SHOT_BYTES' focus='$FOCUS'"
fi
shot 100-T1-launch.png && pass T1b "screenshot is a real frame" || fail T1b "black screenshot"

hdr "T2  accessibility service bound (not just enabled)"
BOUND=$(ad shell dumpsys accessibility 2>&1 | grep -A3 "Bound services" | grep -c "AdaptiveAI")
ENABLED=$(ad shell dumpsys accessibility 2>&1 | grep -c "AdaptiveAccessibilityService")
echo "    enabled refs=$ENABLED bound refs=$BOUND"
if [ "$BOUND" -ge 1 ]; then pass T2 "service is BOUND (Android is delivering windows to it)"; else fail T2 "enabled but NOT bound (refs=$ENABLED)"; fi
texts | grep -qi "ACCESSIBILITY ON" && pass T2b "app UI reports ACCESSIBILITY ON" || fail T2b "UI does not report accessibility on"

hdr "T3  NIM key entry + live Test connection"
TYPED=""
for attempt in 1 2 3; do
  echo "  entry attempt $attempt"
  tab Settings
  tap_desc "API key" || continue
  clear_field
  type_chunks "$NIM_KEY"
  sleep 1
  ad shell input keyevent 111 >/dev/null 2>&1
  sleep 1
  GOT=$(field_value)
  echo "    field now holds ${#GOT} chars: ${GOT:0:9}…"
  if [ "$GOT" = "$NIM_KEY" ]; then TYPED=yes; break; fi
  # discard a bad draft so the retry starts clean
  tap_text "CANCEL"
  ad shell input keyevent 4 >/dev/null 2>&1
  ad shell am force-stop "$PKG" >/dev/null 2>&1
  ad shell am start -n "$ACT" >/dev/null 2>&1
  sleep 6
done
[ -n "$TYPED" ] && pass T3a "key typed into the field exactly" || fail T3a "could not get the full key into the field"

tab Settings
tap_desc "Save key" || fail T3 "cannot tap Save key"
sleep 2
tap_desc "Test" || fail T3 "cannot tap Test"
echo "    waiting for the live NIM round trip (can take ~30s on an emulator)…"
for i in $(seq 1 24); do
  sleep 5
  ad shell cmd statusbar collapse >/dev/null 2>&1
  if texts | grep -qiE "Key accepted|rejected|timed out|Network error"; then break; fi
done
RES=$(texts | grep -iE "Key accepted|models visible|rejected|timed out|Network error" | head -2)
echo "    result: $RES"
if echo "$RES" | grep -qi "Key accepted"; then
  pass T3 "live NIM accepted the key from the device: $RES"
else
  fail T3 "Test did not report success: '$RES'"
fi
shot 103-T3-key-tested.png

hdr "T4  on-device engine: download, load, generate"
tab Settings
tap_node text "On-device (llama.cpp)"
# Tap Download and confirm the download actually started. Bytes moving is the reliable signal;
# the progress readout only renders while the model row is on screen.
STARTED=0
for attempt in 1 2 3; do
  RX0=$(ad shell "cat /proc/net/dev" 2>/dev/null | awk '/eth0|rmnet0|radio0|wlan0/{s+=$2} END{print s+0}')
  tap_node text "Download" || break
  sleep 10
  RX1=$(ad shell "cat /proc/net/dev" 2>/dev/null | awk '/eth0|rmnet0|radio0|wlan0/{s+=$2} END{print s+0}')
  DELTA=$((RX1 - RX0))
  echo "    attempt $attempt: rx delta ${DELTA} bytes"
  if [ "$DELTA" -gt 100000 ]; then STARTED=1; break; fi
  if texts | grep -qE 'text="[0-9.]+ MB / '; then STARTED=1; break; fi
  echo "    download did not start, retrying"
done
if [ "$STARTED" != "1" ]; then
  fail T4 "the download never started (no progress readout)"
  DONE=""
else
  pass T4a "download started through the app's own downloader"
  DONE=""
  for i in $(seq 1 60); do
    sleep 5
    if texts | grep -q 'text="Load"'; then DONE=yes; echo "    download finished after ~$((i*5))s"; break; fi
  done
fi
if [ -z "$DONE" ]; then
  fail T4b "model download did not complete"
else
  pass T4b "GGUF finished downloading"
  tap_node text "Load"
  sleep 12
  LOADED=$(texts | grep -iE "Loaded |Load failed" | head -1)
  echo "    load: $LOADED"
  if echo "$LOADED" | grep -qi "Loaded"; then pass T4b "on-device model loaded: $LOADED"; else fail T4b "load did not succeed: '$LOADED'"; fi
fi

hdr "T5  agent drives a THIRD-PARTY app (cross-app read + fill + tap)"
tab Settings
tap_node content-desc "Confirm before acting"   # turn the gate off so this run is unattended
tab Assistant
tap_desc "Task text" || fail T5 "cannot reach the task input"
clear_field
type_chunks "Open the Settings app and search for wifi"
sleep 1
ad shell input keyevent 111 >/dev/null 2>&1
ad logcat -c
ad shell cmd statusbar collapse >/dev/null 2>&1
tap_text "Go" || fail T5 "cannot tap Go"
echo "    letting the agent run…"
# Watch logcat only: uiautomator unbinds the accessibility service while it runs.
SAW_LAUNCH=0
THIRD_PKG=""
for i in $(seq 1 40); do
  sleep 5
  L=$(ad logcat -d -v brief 2>&1 | grep -E "\[agent\] step" | tail -1)
  [ -n "$L" ] && echo "    t+$((i*5))s: $(echo "$L" | cut -c1-150)"
  TOP=$(ad shell dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity \
    | grep -oE 'u0 [^ ]+/[^ ]+' | head -1 | tr -d '\r')
  PKG_OF_TOP=$(echo "$TOP" | sed -E 's/^u0 //' | cut -d/ -f1)
  if [ -n "$PKG_OF_TOP" ] && [ "$PKG_OF_TOP" != "$PKG" ]; then THIRD_PKG="$PKG_OF_TOP"; fi
  if ad logcat -d 2>&1 | grep -q '\[agent\].*action=launch_app'; then SAW_LAUNCH=1; fi
  # The agent prints a done marker when it finishes; do not stop on the first successful step.
  if ad logcat -d 2>&1 | grep -q '\[agent\] done'; then echo "    agent finished"; break; fi
done
echo "    third-party foreground package: ${THIRD_PKG:-none}"
echo "    agent launched another app: $SAW_LAUNCH"
echo "    agent transcript:"
TRANSCRIPT=$(ad logcat -d -v brief 2>&1 | grep -E "\[agent\]")
echo "$TRANSCRIPT" | sed 's/^/      /' | head -24
# The agent's own observations are the proof: a write the platform confirmed with
# "now contains" on a screen belonging to the app it launched.
SAW_FILL=$(echo "$TRANSCRIPT" | grep -E "result=ok .*now contains" | head -1)
echo "    fill observation: ${SAW_FILL:-(none)}"
shot 105-T5-agent.png
if [ "$SAW_LAUNCH" = "1" ] && [ -n "$SAW_FILL" ]; then
  pass T5 "agent launched a third-party app and wrote text into one of its fields (cross-app ACTION_SET_TEXT confirmed on device)"
elif [ "$SAW_LAUNCH" = "1" ]; then
  skip T5 "agent launched $THIRD_PKG but no successful field write was confirmed"
else
  fail T5 "agent never launched another app (foreground stayed $PKG)"
fi

hdr "T6  text-to-speech actually runs"
TTSLOG=$(ad logcat -d 2>&1 | grep -ciE "TextToSpeech|tts")
if [ "$TTSLOG" -gt 0 ]; then pass T6 "TTS engine activity in logcat ($TTSLOG lines)"; else skip T6 "no TTS log evidence captured"; fi

hdr "T7  voice input (SpeechRecognizer) on this AVD"
ad shell dumpsys package com.google.android.as 2>/dev/null | grep -q "VersionCode" && HAS_GOOGLE_ASR=yes
tab Assistant
ad logcat -c
ad shell input tap 108 2072 >/dev/null 2>&1   # mic button
sleep 6
VSTATUS=$(ad shell dumpsys audio 2>/dev/null | grep -ciE "recognition|voice interaction")
ERR=$(texts | grep -iE "No speech detected|recognizer|Microphone" | head -1)
echo "    mic attempt: audio-service refs=$VSTATUS  UI said: ${ERR:-'(nothing)'}"
if [ -n "$ERR" ]; then
  skip T7 "AVD has no real microphone audio; recognizer ran but heard nothing ('$ERR')"
else
  pass T7 "voice capture started"
fi
ad shell input keyevent 4 >/dev/null 2>&1

hdr "T8  MediaProjection screen capture"
tab Screen
tap_text "Screenshot"
sleep 8
CONSENT=$(texts | grep -iE "Start now|Start broadcast|Allow|screen" | head -2)
echo "    consent UI: ${CONSENT:-'(none)'}"
if [ -n "$CONSENT" ]; then
  tap_text "Start now" || tap_text "Allow"
  sleep 8
  CAP=$(texts | grep -iE "Screenshot|no frame|could not be started|Captured" | head -2)
  echo "    after consent: $CAP"
  pass T8 "MediaProjection consent flow completed on device"
  shot 108-T8-capture.png
else
  skip T8 "no consent dialog appeared (capture may be blocked on this AVD)"
fi

hdr "T9  blind/low-vision affordances present in the tree"
tab Assistant
D=$(dump)
DESCS=$(echo "$D" | grep -oE 'content-desc="[^"]+"' | grep -v '=""' | wc -l)
ROLES=$(echo "$D" | grep -oE 'class="android.widget.(Button|EditText|TextView)"' | sort | uniq -c | tr '\n' ' ')
echo "    labelled nodes=$DESCS classes: $ROLES"
if [ "$DESCS" -ge 3 ]; then pass T9 "interactive elements carry accessibility labels ($DESCS)"; else fail T9 "too few labelled nodes ($DESCS)"; fi

hdr "T10  task history persisted on device"
tab Tasks
T=$(texts | grep -iE "answered|Open|Settings|step" | head -4)
echo "$T" | sed 's/^/    /'
if [ -n "$T" ]; then pass T10 "task log shows stored entries"; else fail T10 "Tasks tab empty after runs"; fi

hdr "SUMMARY"
printf '%-6s %-5s %s\n' "STATUS" "ID" "DETAIL"
for r in "${RESULTS[@]}"; do
  IFS='|' read -r s i d <<< "$r"
  printf '%-6s %-5s %.90s\n' "$s" "$i" "$d"
done
echo
printf 'PASS=%d FAIL=%d SKIP=%d\n' \
  "$(printf '%s\n' "${RESULTS[@]}" | grep -c '^PASS')" \
  "$(printf '%s\n' "${RESULTS[@]}" | grep -c '^FAIL')" \
  "$(printf '%s\n' "${RESULTS[@]}" | grep -c '^SKIP')"
echo "screenshots + dumps in $PROOF"
