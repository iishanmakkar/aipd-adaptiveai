#!/usr/bin/env bash
# Proves the ON-DEVICE engine end to end through the real UI:
#   switch engine to local -> download a GGUF -> load it -> run a task -> show that steps were
#   answered locally with their latency.
#
# Nothing here downloads unless the Download button is tapped below; models are opt-in by design.
set -uo pipefail

ADB="${ADB:-$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROOF="$ROOT/.proof"
mkdir -p "$PROOF"

step() { printf '\n=== %s ===\n' "$1"; }

dump() {
  # An open notification shade steals focus and makes uiautomator dump the shade instead of
  # the app, which looks exactly like "the UI rendered nothing".
  "$ADB" shell cmd statusbar collapse >/dev/null 2>&1
  sleep 1
  "$ADB" shell uiautomator dump //sdcard/ui.xml >/dev/null 2>&1
  "$ADB" shell cat //sdcard/ui.xml 2>/dev/null | tr '>' '>\n'
}

tap_text() {
  local bounds l t r b
  bounds=$(dump | grep -- "text=\"$1\"" | grep -oE 'bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' | head -1 \
    | sed -E 's/bounds="\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]"/\1 \2 \3 \4/')
  [ -n "$bounds" ] || { echo "  (not found: $1)"; return 1; }
  read -r l t r b <<< "$bounds"
  echo "  tap \"$1\" at $(( (l+r)/2 )),$(( (t+b)/2 ))"
  "$ADB" shell input tap $(( (l+r)/2 )) $(( (t+b)/2 )) >/dev/null 2>&1
  sleep 2
}

scroll_top() { for i in 1 2 3; do "$ADB" shell input swipe 540 700 540 2100 250; sleep 1; done; }
scroll_down() { "$ADB" shell input swipe 540 1800 540 700 250; sleep 1; }

# uiautomator only reports visible nodes, so search down the list until the label appears.
tap_text_scrolled() {
  local k
  scroll_top
  for k in 0 1 2 3 4 5; do
    if tap_text "$1"; then return 0; fi
    scroll_down
  done
  return 1
}

step "0. wake + Settings tab"
"$ADB" shell svc power stayon true >/dev/null 2>&1
"$ADB" shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1
"$ADB" shell am force-stop com.android.chrome >/dev/null 2>&1
"$ADB" shell input tap 945 2257; sleep 2
for i in 1 2 3; do "$ADB" shell input swipe 540 700 540 2100 250; sleep 1; done

step "1. select on-device engine"
tap_text_scrolled "On-device (llama.cpp)"

step "2. start the Qwen2.5 0.5B download (first Download button)"
tap_text_scrolled "Download" || { echo "FAIL: no Download button"; exit 1; }

step "3. wait for the download to finish (Load button appears)"
FOUND=""
for i in $(seq 1 60); do
  scroll_top
  for k in 0 1 2 3 4 5; do
    D=$(dump)
    PROG=$(echo "$D" | grep -oE 'text="[0-9.]+ MB / [0-9.]+ MB"' | head -1)
    [ -n "$PROG" ] && echo "  progress: $PROG"
    if echo "$D" | grep -q 'text="Load"'; then FOUND=yes; break; fi
    scroll_down
  done
  if [ -n "$FOUND" ]; then echo "  download complete after ~$((i * 8))s"; break; fi
  sleep 5
done
[ -n "$FOUND" ] || { echo "FAIL: download did not complete in time"; exit 1; }

step "4. load the model"
tap_text_scrolled "Load"
sleep 10
dump | grep -oE 'text="[^"]+"' | grep -v '=""' | grep -iE "Loaded|Load failed|Unload" | head -3

step "4b. turn OFF confirm-before-acting so the run is unattended"
"$ADB" shell input tap 945 2257; sleep 2
scroll_top
FOUND_TOGGLE=""
for k in 0 1 2 3 4 5 6; do
  BOUNDS=$(dump | grep -- 'content-desc="Confirm before acting"' \
    | grep -oE 'bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' | head -1 \
    | sed -E 's/bounds="\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]"/\1 \2 \3 \4/')
  if [ -n "$BOUNDS" ]; then
    read -r l t r b <<< "$BOUNDS"
    "$ADB" shell input tap $(( (l+r)/2 )) $(( (t+b)/2 )); sleep 2
    echo "  toggled confirm-before-acting off"
    FOUND_TOGGLE=yes
    break
  fi
  scroll_down
done
[ -n "$FOUND_TOGGLE" ] || echo "  warning: could not find the confirm toggle"

step "5. run a task on the local engine"
"$ADB" shell input tap 135 2257; sleep 2
tap_text_node() { :; }
BOUNDS=$(dump | grep -- 'content-desc="Task text"' | grep -oE 'bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' | head -1 \
  | sed -E 's/bounds="\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]"/\1 \2 \3 \4/')
read -r l t r b <<< "$BOUNDS"
"$ADB" shell input tap $(( (l+r)/2 )) $(( (t+b)/2 )); sleep 1
"$ADB" shell input text "Open+the+Settings+app+and+read+what+is+on+the+screen"; sleep 1
"$ADB" shell input keyevent 111; sleep 1
tap_text "Go"

step "6. let the local agent run, then read the log once the window is idle"
sleep 100
dump | grep -oE 'text="[^"]+"' | grep -v '=""' | grep -iE "answered by|ACTION|OBSERVE|Step|stopped|failed" | head -16

step "7. final log + screenshot"
dump | grep -oE 'text="[^"]+"' | grep -v '=""' | head -24
"$ADB" exec-out screencap -p > "$PROOF/30-local-engine.png" 2>/dev/null
echo "saved .proof/30-local-engine.png ($(wc -c < "$PROOF/30-local-engine.png") bytes)"
