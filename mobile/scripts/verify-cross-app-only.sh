#!/usr/bin/env bash
# Focused proof: the agent, running the shipped code with a live NIM key, opens a real third-party
# app and writes into one of its fields.
#
# Ordering matters. The confirm gate is a modal inside our own app, so finding it needs a view
# dump — and dumping makes Android unbind the accessibility service. The agent retries a screen
# read for a few seconds, which covers the rebind, so the gate can be approved safely.
set -uo pipefail

ADB="${ADB:-$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe}"
S="${ADB_SERIAL:-emulator-5554}"
PKG=com.adaptiveai
ACT="$PKG/$PKG.mobile.MainActivity"
SVC="$PKG/$PKG.mobile.assist.AdaptiveAccessibilityService"
ROOT=/d/aipd/mobile
K="${NIM_KEY:?set NIM_KEY}"

ad() { "$ADB" -s "$S" "$@"; }
fb() {
  ad shell cmd statusbar collapse >/dev/null 2>&1; sleep 1
  ad shell uiautomator dump //sdcard/ui.xml >/dev/null 2>&1
  ad shell "cat //sdcard/ui.xml" | sed -E 's|<node |\n<node |g'
}
tb() {
  local B; B=$(fb | grep -- "$1" | grep -oE 'bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' | head -1 \
    | sed -E 's/bounds="\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]"/\1 \2 \3 \4/')
  [ -z "$B" ] && return 1
  local l t r b; read -r l t r b <<< "$B"
  ad shell input tap $(( (l+r)/2 )) $(( (t+b)/2 )) >/dev/null 2>&1
  echo "    tapped $1 @ $(( (l+r)/2 )),$(( (t+b)/2 ))"; sleep 2; return 0
}
type_chunks() {
  local s="$1" i
  for i in $(seq 0 4 ${#s}); do ad shell input text "\"${s:$i:4}\"" >/dev/null 2>&1; sleep 0.4; done
}

echo "=== 1. clean install ==="
# install -r keeps SecureStore (the NIM key) and any downloaded model. The stale-SoLoader
# problem only appears when native libraries change, and this build changed none.
ad install -r "$ROOT/android/app/build/outputs/apk/release/app-release.apk" 2>&1 | tail -1
ad shell pm grant "$PKG" android.permission.RECORD_AUDIO 2>/dev/null
ad shell svc power stayon true >/dev/null 2>&1
ad shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1
ad shell am start -n "$ACT" >/dev/null 2>&1; sleep 9

echo "=== 2. NIM key (skipped if already stored) ==="
ad shell input tap 945 2257 >/dev/null 2>&1; sleep 3
if fb | grep -q 'text="NO NIM KEY"'; then
  for i in 1 2 3 4; do ad shell input swipe 540 600 540 2200 300 >/dev/null 2>&1; sleep 1; done
  tb 'content-desc="API key"'
  for i in $(seq 1 30); do ad shell input keyevent 67 >/dev/null 2>&1; done
  type_chunks "$K"
  ad shell input keyevent 111 >/dev/null 2>&1; sleep 1
  tb 'content-desc="Save key"'
  tb 'content-desc="Test"'
  sleep 28
  RES=$(fb | grep -oE 'text="[^"]*(Key accepted|models visible)[^"]*"' | head -1)
  echo "    $RES"
else
  echo "    key already stored on this device"
fi

echo "=== 3. disable the confirm gate (dumps are safe before the service is enabled) ==="
for i in 1 2 3 4 5 6 7 8; do
  ad shell input swipe 540 1800 540 700 250 >/dev/null 2>&1; sleep 1
done
tb 'content-desc="Confirm before acting"'

echo "=== 4. enable accessibility LAST ==="
ad shell settings put secure enabled_accessibility_services "$SVC"
ad shell settings put secure accessibility_enabled 1
sleep 4
ad shell am force-stop "$PKG"; sleep 2
ad shell am start -n "$ACT" >/dev/null 2>&1; sleep 8
echo "    bound refs: $(ad shell dumpsys accessibility 2>&1 | sed -n '/Bound services/,/Enabled/p' | grep -c AdaptiveAI)"

echo "=== 5. run the task ==="
ad shell input tap 135 2257 >/dev/null 2>&1; sleep 2
tb 'content-desc="Task text"'
for i in $(seq 1 70); do ad shell input keyevent 67 >/dev/null 2>&1; done
type_chunks "Open the Settings app and search for wifi"
ad shell input keyevent 111 >/dev/null 2>&1; sleep 1
ad logcat -c
tb 'text="Go"'
LAST_STEPS=0
STALLED=0
for i in $(seq 1 40); do
  sleep 5
  STEPS=$(ad logcat -d 2>&1 | grep -c "\[agent\] step")
  if [ "$STEPS" -gt "$LAST_STEPS" ]; then
    LAST_STEPS=$STEPS
    STALLED=0
    echo "    t+$((i*5))s steps=$STEPS: $(ad logcat -d -v brief 2>&1 | grep -E '\[agent\] step' | tail -1 | cut -c1-150)"
  else
    STALLED=$((STALLED+1))
    # No new step for 10s: the agent is most likely waiting at the confirm gate.
    if [ "$STALLED" -ge 2 ]; then
      if tb 'text="Do it"'; then echo "    approved the confirm gate"; STALLED=0; else STALLED=0; fi
    fi
  fi
  if ad logcat -d 2>&1 | grep -q '\[agent\] done'; then echo "    agent finished"; break; fi
done

echo "=== 6. transcript ==="
ad logcat -d -v brief 2>&1 | grep -E "\[agent\]" | sed 's/.*\[agent\]/[agent]/' | head -30
echo "=== 7. final foreground ==="
ad shell dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity | tr -d '\r'
ad exec-out screencap -p > "$ROOT/.proof/220-cross-app.png" 2>/dev/null
echo "    saved .proof/220-cross-app.png ($(wc -c < "$ROOT/.proof/220-cross-app.png") bytes)"
