#!/usr/bin/env bash
# Final on-device proof sequence. Installs ONCE — reinstalling wipes SecureStore (the NIM key)
# and the accessibility grant, which is what made earlier runs silently do nothing.
#
# Order matters:
#   key entry and the gate toggle use uiautomator (safe: the service is not needed yet),
#   accessibility is enabled LAST, and the agent run is verified from logcat only, because
#   `uiautomator dump` unbinds the accessibility service while it runs.
set -uo pipefail

ADB="${ADB:-$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe}"
S="${ADB_SERIAL:-emulator-5554}"
PKG=com.adaptiveai
ACT="$PKG/$PKG.mobile.MainActivity"
SVC="$PKG/$PKG.mobile.assist.AdaptiveAccessibilityService"
ROOT=/d/aipd/mobile
APK="$ROOT/android/app/build/outputs/apk/release/app-release.apk"
K="${NIM_KEY:?set NIM_KEY}"

ad() { "$ADB" -s "$S" "$@"; }
fb() {
  ad shell cmd statusbar collapse >/dev/null 2>&1; sleep 1
  ad shell uiautomator dump //sdcard/ui.xml >/dev/null 2>&1
  ad shell "cat //sdcard/ui.xml" | sed -E 's|<node |\n<node |g' | grep -- "$1" \
    | grep -oE 'bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' | head -1 \
    | sed -E 's/bounds="\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]"/\1 \2 \3 \4/'
}
tb() { B=$(fb "$1"); [ -z "$B" ] && { echo "    MISSING $1"; return 1; }; read l t r b <<< "$B"; ad shell input tap $(( (l+r)/2 )) $(( (t+b)/2 )) >/dev/null 2>&1; echo "    tapped $1 @ $(( (l+r)/2 )),$(( (t+b)/2 ))"; sleep 2; }
dismiss() { B=$(fb 'text="OK"'); [ -n "$B" ] && { read l t r b <<< "$B"; ad shell input tap $(( (l+r)/2 )) $(( (t+b)/2 )) >/dev/null 2>&1; sleep 2; echo "    dismissed dialog"; }; }
texts() { ad shell "cat //sdcard/ui.xml" | sed -E 's|<node |\n<node |g' | grep -oE 'text="[^"]+"' | grep -v '=""'; }

echo "=== 1. single clean install ==="
ad uninstall "$PKG" >/dev/null 2>&1
ad install "$APK" 2>&1 | tail -1
ad shell pm grant "$PKG" android.permission.RECORD_AUDIO 2>/dev/null
ad shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS 2>/dev/null
ad shell svc power stayon true >/dev/null 2>&1
ad shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1
ad shell am start -n "$ACT" >/dev/null 2>&1; sleep 9

echo "=== 2. enter NIM key and verify it is stored ==="
ad shell input tap 945 2257 >/dev/null 2>&1; sleep 3
for i in 1 2 3 4; do ad shell input swipe 540 600 540 2200 300 >/dev/null 2>&1; sleep 1; done
dismiss
tb 'content-desc="API key"'
for i in $(seq 1 30); do ad shell input keyevent 67 >/dev/null 2>&1; done
for i in $(seq 0 4 ${#K}); do ad shell input text "\"${K:$i:4}\"" >/dev/null 2>&1; sleep 0.4; done
ad shell cmd statusbar collapse >/dev/null 2>&1; ad shell uiautomator dump //sdcard/ui.xml >/dev/null 2>&1
V=$(ad shell "cat //sdcard/ui.xml" | sed -E 's|<node |\n<node |g' | grep -- 'content-desc="API key"' | grep -oE 'text="[^"]*"' | head -1)
echo "    field: ${V:0:20}… len=${#V}"
ad shell input keyevent 111 >/dev/null 2>&1; sleep 1
tb 'content-desc="Save key"'
ad shell cmd statusbar collapse >/dev/null 2>&1; ad shell uiautomator dump //sdcard/ui.xml >/dev/null 2>&1
texts | grep -qiE "does not look right|Nothing to save" && { echo "    save rejected; retrying"; dismiss; }

echo "=== 3. live Test connection ==="
tb 'content-desc="Test"'
echo "    waiting for NIM…"
sleep 25
ad shell cmd statusbar collapse >/dev/null 2>&1; ad shell uiautomator dump //sdcard/ui.xml >/dev/null 2>&1
RES=$(texts | grep -iE "Key accepted|rejected|timed out|Network error" | head -1)
echo "    TEST RESULT: $RES"

echo "=== 4. turn the confirm gate off (dumps still safe here) ==="
for i in 1 2 3 4 5 6 7; do ad shell input swipe 540 1800 540 700 250 >/dev/null 2>&1; sleep 1; done
tb 'content-desc="Confirm before acting"' && echo "    gate disabled"

echo "=== 5. enable accessibility LAST ==="
ad shell settings put secure enabled_accessibility_services "$SVC"
ad shell settings put secure accessibility_enabled 1
sleep 4
ad shell am force-stop "$PKG"; sleep 2
ad shell am start -n "$ACT" >/dev/null 2>&1; sleep 8
BOUND=$(ad shell dumpsys accessibility 2>&1 | sed -n '/Bound services/,/Enabled/p' | grep -c AdaptiveAI)
echo "    bound refs=$BOUND"

echo "=== 6. run the task; verify from logcat only (no dumps) ==="
ad shell input tap 135 2257 >/dev/null 2>&1; sleep 2
ad shell input tap 522 2072 >/dev/null 2>&1; sleep 2
for i in $(seq 1 70); do ad shell input keyevent 67 >/dev/null 2>&1; done
ad shell input text "Open%sthe%sSettings%sapp%sand%ssearch%sfor%swifi" >/dev/null 2>&1
sleep 1
ad shell input keyevent 111 >/dev/null 2>&1; sleep 1
ad shell logcat -c
ad shell input tap 954 2072 >/dev/null 2>&1
echo "    GO at $(date +%T)"
for i in $(seq 1 24); do
  sleep 5
  N=$(ad logcat -d 2>&1 | grep -c "\[agent\] step")
  TOP=$(ad shell dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity | grep -oE 'u0 [^/.]+' | tail -1 | tr -d '\r')
  echo "    t+$((i*5))s agent_steps=$N foreground=$TOP"
  [ "$N" -ge 6 ] && break
done

echo "=== 7. agent transcript ==="
ad logcat -d -v brief 2>&1 | grep -E "\[agent\]" | sed 's/^/  /' | head -30
echo "=== 8. final state ==="
ad shell dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity | tr -d '\r'
ad shell cmd statusbar collapse >/dev/null 2>&1
ad shell uiautomator dump //sdcard/ui.xml >/dev/null 2>&1
texts | head -16
ad exec-out screencap -p > "$ROOT/.proof/210-final-agent.png" 2>/dev/null
echo "    saved .proof/210-final-agent.png ($(wc -c < "$ROOT/.proof/210-final-agent.png") bytes)"
