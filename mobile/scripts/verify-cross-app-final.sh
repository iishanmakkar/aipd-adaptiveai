#!/usr/bin/env bash
# Cross-app proof on a device whose accessibility service is bound and stable.
# No reinstall (that wedges the system accessibility service), no dumps while the agent runs.
set -uo pipefail
K="${NIM_KEY:?set NIM_KEY}"
ADB="${ADB:-$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe}"
S="${ADB_SERIAL:-emulator-5554}"
PKG=com.adaptiveai
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
type_chunks() { local s="$1" i; for i in $(seq 0 4 ${#s}); do ad shell input text "\"${s:$i:4}\"" >/dev/null 2>&1; sleep 0.4; done; }

echo "=== preconditions ==="
echo "  bound: $(ad shell dumpsys accessibility 2>&1 | sed -n '/Bound services/,/Enabled/p' | grep -c AdaptiveAI)"
echo "  key stored: $(fb | grep -c 'text="NIM KEY SET"')"

if [ "$(fb | grep -c 'text="NIM KEY SET"')" = "0" ]; then
  echo "=== entering the NIM key ==="
  ad shell input tap 945 2257 >/dev/null 2>&1; sleep 3
  for i in 1 2 3 4; do ad shell input swipe 540 600 540 2200 300 >/dev/null 2>&1; sleep 1; done
  tb 'content-desc="API key"'
  for i in $(seq 1 30); do ad shell input keyevent 67 >/dev/null 2>&1; done
  type_chunks "$NIM_KEY"
  ad shell input keyevent 111 >/dev/null 2>&1; sleep 1
  tb 'content-desc="Save key"'
  tb 'content-desc="Test"'
  sleep 30
  echo "  $(fb | grep -oE 'text="[^"]*(Key accepted|models visible)[^"]*"' | head -1)"
  ad shell input tap 135 2257 >/dev/null 2>&1; sleep 2
  echo "  bound after key entry: $(ad shell dumpsys accessibility 2>&1 | sed -n '/Bound services/,/Enabled/p' | grep -c AdaptiveAI)"
fi

echo "=== start the task ==="
ad shell input tap 135 2257 >/dev/null 2>&1; sleep 2
tb 'content-desc="Task text"'
for i in $(seq 1 70); do ad shell input keyevent 67 >/dev/null 2>&1; done
type_chunks "Open the Settings app and search for wifi"
ad shell input keyevent 111 >/dev/null 2>&1; sleep 1
ad logcat -c
tb 'text="Go"'
LAST=0; STALL=0
for i in $(seq 1 40); do
  sleep 5
  N=$(ad logcat -d 2>&1 | grep -c "\[agent\] step")
  if [ "$N" -gt "$LAST" ]; then
    LAST=$N; STALL=0
    echo "    t+$((i*5))s: $(ad logcat -d -v brief 2>&1 | grep -E '\[agent\] step' | tail -1 | cut -c1-160)"
  else
    STALL=$((STALL+1))
    if [ "$STALL" -ge 2 ]; then
      if tb 'text="Do it"'; then echo "    approved the confirm gate"; fi
      STALL=0
    fi
  fi
  if ad logcat -d 2>&1 | grep -q '\[agent\] done'; then echo "    agent finished"; break; fi
done
echo "=== transcript ==="
ad logcat -d -v brief 2>&1 | grep -E "\[agent\]" | sed 's/.*\[agent\]/[agent]/' | head -30
echo "=== foreground ==="
ad shell dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity | tr -d '\r'
ad exec-out screencap -p > /d/aipd/mobile/.proof/230-cross-app-final.png 2>/dev/null
echo "  saved .proof/230-cross-app-final.png ($(wc -c < /d/aipd/mobile/.proof/230-cross-app-final.png) bytes)"
