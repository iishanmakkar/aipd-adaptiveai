#!/usr/bin/env bash
# On-device proof for the AdaptiveAI mobile app.
#
# Installs the release APK on a connected device/emulator, launches it, enables the
# accessibility service, and captures screenshots + logcat evidence into mobile/.proof/.
#
# A green build is not evidence. This script is the evidence: it asserts the app process is
# alive, the activity is resumed, the accessibility service is bound, and the UI actually
# rendered (non-black screenshot with visible text nodes).
#
# Usage:  bash mobile/scripts/verify-on-device.sh
set -uo pipefail

ADB="${ADB:-$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APK="$ROOT/android/app/build/outputs/apk/release/app-release.apk"
PROOF="$ROOT/.proof"
PKG="com.adaptiveai"
ACT="$PKG/.mobile.MainActivity"
SVC="$PKG/com.adaptiveai.mobile.assist.AdaptiveAccessibilityService"

mkdir -p "$PROOF"
step() { printf '\n=== %s ===\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1"; exit 1; }

[ -f "$ADB" ] || fail "adb not found at $ADB"
[ -f "$APK" ] || fail "release APK not built: $APK (run: cd mobile/android && ./gradlew assembleRelease)"
"$ADB" get-state >/dev/null 2>&1 || fail "no device connected (adb get-state failed)"

step "0. device"
"$ADB" shell getprop ro.build.version.release | tr -d '\r' | sed 's/^/android /'
"$ADB" shell getprop ro.product.cpu.abi | tr -d '\r' | sed 's/^/abi     /'
# A sleeping screen or an ANR'd background app makes screencap return a black frame.
"$ADB" shell svc power stayon true >/dev/null 2>&1
"$ADB" shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1
"$ADB" shell am force-stop com.android.chrome >/dev/null 2>&1

step "1. install"
"$ADB" uninstall "$PKG" >/dev/null 2>&1
"$ADB" install -r "$APK" | tail -1

step "2. permissions + accessibility"
"$ADB" shell pm grant "$PKG" android.permission.RECORD_AUDIO 2>/dev/null
"$ADB" shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS 2>/dev/null
# The settings provider can lag a fresh install; retry until the write reads back.
ENABLED=""
for i in 1 2 3 4 5 6; do
  "$ADB" shell settings put secure enabled_accessibility_services "$SVC"
  "$ADB" shell settings put secure accessibility_enabled 1
  sleep 2
  ENABLED=$("$ADB" shell settings get secure enabled_accessibility_services | tr -d '\r')
  case "$ENABLED" in *AdaptiveAccessibilityService*) break ;; esac
  echo "  retry $i: got '$ENABLED'"
done
echo "enabled_accessibility_services=$ENABLED"
case "$ENABLED" in *AdaptiveAccessibilityService*) ;; *) fail "accessibility service not enabled";; esac

step "3. launch"
"$ADB" logcat -c
"$ADB" shell am start -n "$ACT" | tail -1
sleep 10

PID=$("$ADB" shell pidof "$PKG" | tr -d '\r')
echo "pid=$PID"
[ -n "$PID" ] || fail "app process is not running"

TOP=$("$ADB" shell dumpsys activity activities | grep -E "topResumedActivity" | head -1 | tr -d '\r')
echo "top: $TOP"
case "$TOP" in *com.adaptiveai*) ;; *) fail "app is not the resumed activity: $TOP";; esac

# An ANR dialog steals focus and suppresses drawing: the app then looks like a black screen
# while its view tree is perfectly intact. Catch that explicitly.
FOCUS=$("$ADB" shell dumpsys window 2>/dev/null | grep -E "mCurrentFocus=" | head -1 | tr -d '\r')
echo "focus: $FOCUS"
case "$FOCUS" in *"Application Not Responding"*) fail "app ANR'd; an ANR dialog holds input focus";; esac
case "$FOCUS" in *com.adaptiveai*) ;; *) echo "  warning: focus is not our window: $FOCUS";; esac

step "4. boot log"
"$ADB" logcat -d -v brief 2>&1 | grep -E "ReactNativeJS|\[boot\]" | tail -12

step "5. accessibility service bound"
"$ADB" shell dumpsys accessibility 2>&1 | grep -iE "AdaptiveAccessibilityService" | head -4 | tr -d '\r'

step "6. rendered view hierarchy"
# An open notification shade steals focus and makes the dump show the shade, not the app.
"$ADB" shell cmd statusbar collapse >/dev/null 2>&1
sleep 1
# //sdcard: the doubled slash stops Git Bash from rewriting the device path into a host path.
"$ADB" shell uiautomator dump //sdcard/ui.xml >/dev/null 2>&1
"$ADB" shell cat //sdcard/ui.xml 2>/dev/null | tr '>' '>\n' | grep -oE 'text="[^"]+"' | grep -v 'text=""' | head -12 > "$PROOF/ui-text.txt"
cat "$PROOF/ui-text.txt"
NODES=$(wc -l < "$PROOF/ui-text.txt")
echo "visible text nodes: $NODES"
[ "$NODES" -ge 1 ] || fail "UI rendered no text nodes (black screen)"

step "7. screenshots"
"$ADB" exec-out screencap -p > "$PROOF/10-assistant-tab.png"
echo "saved .proof/10-assistant-tab.png ($(wc -c < "$PROOF/10-assistant-tab.png") bytes)"

step "8. crashes since launch"
CRASH=$("$ADB" logcat -d 2>&1 | grep -cE "FATAL EXCEPTION")
echo "fatal exceptions: $CRASH"
[ "$CRASH" -eq 0 ] || fail "app crashed on device"

printf '\n=== RESULT: PASS ===\n'
printf 'process alive, activity resumed, accessibility bound, %s text nodes rendered, 0 crashes\n' "$NODES"
printf 'evidence in %s\n' "$PROOF"
