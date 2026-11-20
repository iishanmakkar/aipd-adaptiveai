#!/usr/bin/env bash
# Cross-app agent proof, gated on observed readiness at every step.
#
# Traps this avoids (each one silently broke an earlier attempt):
#   - a second emulator appearing: every command pins -s $S
#   - tapping before the app has drawn: each step waits for the expected node in a dump
#   - reinstalling: wipes SecureStore (the key) and the accessibility grant
#   - uiautomator unbinding the accessibility service: no dumps after accessibility is enabled
set -uo pipefail

ADB="${ADB:-$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe}"
S="${ADB_SERIAL:-emulator-5554}"
PKG=com.adaptiveai
ACT="$PKG/$PKG.mobile.MainActivity"
SVC="$PKG/$PKG.mobile.assist.AdaptiveAccessibilityService"
ROOT=/d/aipd/mobile
K="${NIM_KEY:?set NIM_KEY}"

ad() { "$ADB" -s "$S" "$@"; }
dump_now() { ad shell cmd statusbar collapse >/dev/null 2>&1; ad shell uiautomator dump //sdcard/ui.xml >/dev/null 2>&1; ad shell "cat //sdcard/ui.xml" | sed -E 's|<node |\n<node |g'; }
bounds_of() { dump_now | grep -- "$1" | grep -oE 'bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' | head -1 | sed -E 's/bounds="\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]"/\1 \2 \3 \4/'; }

# Wait until a node exists, then tap its centre. Fails loudly rather than tapping blind.
wait_tap() {
  local attr="$1" value="$2" tries="${3:-12}" B
  for i in $(seq 1 "$tries"); do
    B=$(bounds_of "$attr=\"$value\"")
    if [ -n "$B" ]; then
      read l t r b <<< "$B"
      ad shell input tap $(( (l+r)/2 )) $(( (t+b)/2 )) >/dev/null 2>&1
      echo "    tapped $value @ $(( (l+r)/2 )),$(( (t+b)/2 )) (after ${i}s)"
      sleep 2; return 0
    fi
    sleep 1
  done
  echo "    TIMEOUT waiting for $attr=\"$value\""
  return 1
}

echo "=== 0. exactly one device, app installed ==="
DEVS=$(adb_devices_count() { "$ADB" devices | tail -n +2 | grep -c device; }; adb_devices_count)
echo "    devices attached: $DEVS (targeting $S)"
ad shell pm list packages 2>/dev/null | grep -q "^package:$PKG$" || { echo "    app not installed; installing once"; ad install "$ROOT/android/app/build/outputs/apk/release/app-release.apk" 2>&1 | tail -1; }
ad shell pm grant "$PKG" android.permission.RECORD_AUDIO 2>/dev/null
ad shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS 2>/dev/null
ad shell svc power stayon true >/dev/null 2>&1
ad shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1

echo "=== 1. launch and wait for the Assistant screen ==="
ad shell am start -n "$ACT" >/dev/null 2>&1
wait_tap text "AdaptiveAI" 20 || exit 1

echo "=== 2. go to Settings and enter the key ==="
ad shell input tap 945 2257 >/dev/null 2>&1
wait_tap content-desc "API key" 20 || exit 1
for i in $(seq 1 40); do ad shell input keyevent 67 >/dev/null 2>&1; done
for i in $(seq 0 4 ${#K}); do ad shell input text "\"${K:$i:4}\"" >/dev/null 2>&1; sleep 0.4; done
V=$(dump_now | grep -- 'content-desc="API key"' | grep -oE 'text="[^"]*"' | head -1)
echo "    field holds ${#V} chars (expect $(( ${#K} + 7 ))): ${V:0:18}…"
ad shell input keyevent 111 >/dev/null 2>&1; sleep 1
wait_tap content-desc "Save key" || exit 1

echo "=== 3. live Test ==="
wait_tap content-desc "Test" || exit 1
echo "    waiting for NIM…"
sleep 25
RES=$(dump_now | grep -oE 'text="[^"]+"' | grep -iE "Key accepted|rejected|timed out|Network error" | head -1)
echo "    TEST: $RES"
[ -n "$RES" ] || { echo "    no test result rendered"; }

echo "=== 4. disable the confirm gate ==="
for i in 1 2 3 4 5 6 7; do ad shell input swipe 540 1800 540 700 250 >/dev/null 2>&1; sleep 1; done
wait_tap content-desc "Confirm before acting" 10 || echo "    gate not found (leaving default)"

echo "=== 5. enable accessibility LAST, then never dump again ==="
ad shell settings put secure enabled_accessibility_services "$SVC"
ad shell settings put secure accessibility_enabled 1
sleep 4
ad shell am force-stop "$PKG"; sleep 2
ad shell am start -n "$ACT" >/dev/null 2>&1; sleep 10
BOUND=$(ad shell dumpsys accessibility 2>&1 | sed -n '/Bound services/,/Enabled/p' | grep -c AdaptiveAI)
echo "    bound refs=$BOUND  (dumpsys does not unbind; uiautomator would)"
[ "$BOUND" -ge 1 ] || { echo "    ABORT: service not bound, agent cannot work"; exit 2; }

echo "=== 6. run the task blind; verify only via logcat ==="
ad shell input tap 135 2257 >/dev/null 2>&1; sleep 3      # Assistant tab
ad shell input tap 522 2072 >/dev/null 2>&1; sleep 2      # task field
for i in $(seq 1 70); do ad shell input keyevent 67 >/dev/null 2>&1; done
ad shell input text "Open%sthe%sSettings%sapp%sand%ssearch%sfor%swifi" >/dev/null 2>&1
sleep 1
ad shell input keyevent 111 >/dev/null 2>&1; sleep 1
ad shell logcat -c
ad shell input tap 954 2072 >/dev/null 2>&1
echo "    GO at $(date +%T)"
for i in $(seq 1 30); do
  sleep 5
  N=$(ad logcat -d 2>&1 | grep -c "\[agent\] step")
  FG=$(ad shell dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity | sed -E 's/.*u0 ([^ ]+)\/.*/\1/' | tr -d '\r')
  echo "    t+$((i*5))s steps=$N foreground=$FG"
  [ "$N" -ge 5 ] && break
done

echo "=== 7. transcript ==="
ad logcat -d -v brief 2>&1 | grep -E "\[agent\]" | sed 's/^/  /' | head -30
echo "=== 8. did it reach Settings? ==="
ad shell dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity | tr -d '\r'
