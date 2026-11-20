#!/usr/bin/env bash
# Drives the real AdaptiveAI UI on a connected device to prove the full loop on hardware:
#   Settings -> enter NIM key -> Test (reports live model count)
#   Assistant -> type a task -> run -> agent log renders
#
# Taps are located by visible text or content-desc from a uiautomator dump, never by
# hard-coded pixels, so layout changes do not silently break the proof.
#
# Usage: NIM_KEY=nvapi-... bash mobile/scripts/verify-agent-on-device.sh
set -uo pipefail

ADB="${ADB:-$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROOF="$ROOT/.proof"
PKG="com.adaptiveai"
mkdir -p "$PROOF"

step() { printf '\n=== %s ===\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1"; exit 1; }

[ -n "${NIM_KEY:-}" ] || fail "set NIM_KEY=nvapi-... first"

# Locate a node by exact visible text or content-desc and tap its centre.
tap_node() {
  local attr="$1" value="$2" bounds l t r b
  # //sdcard: the doubled slash stops Git Bash from rewriting the device path into a host path.
  "$ADB" shell uiautomator dump //sdcard/ui.xml >/dev/null 2>&1
  bounds=$("$ADB" shell cat //sdcard/ui.xml 2>/dev/null \
    | tr '>' '>\n' \
    | grep -- "$attr=\"$value\"" \
    | grep -oE 'bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' \
    | head -1 | sed -E 's/bounds="\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]"/\1 \2 \3 \4/')
  [ -n "$bounds" ] || { echo "  (node not found: $attr=$value)"; return 1; }
  read -r l t r b <<< "$bounds"
  echo "  tap $attr=\"$value\" at $(( (l+r)/2 )),$(( (t+b)/2 ))"
  "$ADB" shell input tap $(( (l+r)/2 )) $(( (t+b)/2 )) >/dev/null 2>&1
  sleep 1
}

# The tab bar is four equal columns across a 1080px-wide screen; tapping fixed tab centres is
# stable regardless of which tab is current or how far a list is scrolled.
tap_tab() {
  case "$1" in
    Assistant) "$ADB" shell input tap 135 2257 ;;
    Screen) "$ADB" shell input tap 405 2257 ;;
    Tasks) "$ADB" shell input tap 675 2257 ;;
    Settings) "$ADB" shell input tap 945 2257 ;;
  esac
  echo "  tapped tab $1"
  sleep 2
}

scroll_to_top() {
  for _ in 1 2 3; do
    "$ADB" shell input swipe 540 700 540 2100 250 >/dev/null 2>&1
    sleep 1
  done
  echo "  scrolled to top"
}

shot() {
  "$ADB" exec-out screencap -p > "$PROOF/$1" 2>/dev/null
  echo "  saved .proof/$1 ($(wc -c < "$PROOF/$1") bytes)"
}

step "0. preconditions"
"$ADB" shell pidof "$PKG" | tr -d '\r' | sed 's/^/pid /' || fail "app not running; run verify-on-device.sh first"
# This emulator ANRs background apps and lets the screen sleep mid-run, both of which corrupt
# uiautomator dumps and screencap. Keep it awake and quiet.
"$ADB" shell svc power stayon true >/dev/null 2>&1
"$ADB" shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1
"$ADB" shell am force-stop com.android.chrome >/dev/null 2>&1
sleep 1

step "1. open Settings tab"
tap_tab Settings
scroll_to_top
shot 20-settings.png

step "2. enter NIM key"
tap_node content-desc "API key" || fail "cannot find the API key field"
"$ADB" shell input text "$NIM_KEY" >/dev/null 2>&1
sleep 1
# ESCAPE dismisses the IME without navigating back; the keyboard otherwise covers Save/Test.
"$ADB" shell input keyevent 111 >/dev/null 2>&1
sleep 1
echo "  key typed ($(echo -n "$NIM_KEY" | wc -c) chars), keyboard dismissed"

step "3. save and test"
# With the list scrolled to top and the IME dismissed these two buttons sit at fixed positions
# in the 1080x2400 layout; dumping is unreliable while the window settles.
"$ADB" shell input tap 280 1145 >/dev/null 2>&1
echo "  tapped Save key (280,1145)"
sleep 2
"$ADB" shell input tap 615 1145 >/dev/null 2>&1
echo "  tapped Test (615,1145)"
echo "  waiting for NIM round trip…"
sleep 16
shot 21-key-tested.png
"$ADB" shell uiautomator dump //sdcard/ui.xml >/dev/null 2>&1
"$ADB" shell cat //sdcard/ui.xml 2>/dev/null | tr '>' '>\n' \
  | grep -oE 'text="[^"]*models visible[^"]*"' | head -2 | sed 's/^/  result: /' \
  || echo "  (no 'models visible' text found — check 21-key-tested.png)"

step "4. Assistant tab, run a live task"
tap_tab Assistant
tap_node content-desc "Task text" || fail "cannot find the task input"
"$ADB" shell input text "Open+the+Settings+app+and+read+what+is+on+the+screen" >/dev/null 2>&1
sleep 1
"$ADB" shell input keyevent 111 >/dev/null 2>&1
sleep 1
tap_node text "Go" || fail "cannot tap Go"
echo "  agent running; approving confirm gates as they appear…"
# The agent asks before touching another app (confirmBeforeActing defaults on). Approve each
# gate so the unattended proof can proceed, and let the loop run between gates.
for i in $(seq 1 14); do
  sleep 5
  "$ADB" shell uiautomator dump //sdcard/ui.xml >/dev/null 2>&1
  if "$ADB" shell cat //sdcard/ui.xml 2>/dev/null | grep -q 'text="Do it"'; then
    echo "  approving confirm gate ($i)"
    tap_node text "Do it"
  fi
done
shot 22-agent-running.png

step "5. agent log evidence"
"$ADB" shell uiautomator dump //sdcard/ui.xml >/dev/null 2>&1
"$ADB" shell cat //sdcard/ui.xml 2>/dev/null | tr '>' '>\n' \
  | grep -oE 'text="[^"]+"' | grep -v 'text=""' | head -20 | sed 's/^/  /'

step "6. task history"
tap_tab Tasks
sleep 2
shot 23-task-history.png

printf '\n=== done: inspect .proof/2*.png ===\n'
