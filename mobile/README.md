# AdaptiveAI Mobile

An Android voice agent for **blind and low-vision users** that reads whatever is on screen and
takes a task by voice — opening any app, filling forms, tapping buttons, typing into search boxes,
scrolling, and doing multi-step flows like "search for mr beast on YouTube" or "add apples to the
cart". Everything runs on the phone, driven by the Google **Gemini Flash** free tier.

**There is no AdaptiveAI backend.** The phone talks to
`https://generativelanguage.googleapis.com` directly (the model runs at Google, not on a server
of ours). An API key is pasted into Settings and stored in the Android Keystore — it is never
written in plaintext to storage, and a user-entered key always wins over any embedded one.

This app is independent of the 7-service stack in the repository root. It does not call
`backend/`, `intent-engine/`, `agents/`, or `browser-agent/`.

---

## What it can do

| Capability | How | Where |
| --- | --- | --- |
| Read any app's UI | `AccessibilityService` → serialised node tree | `assist/AdaptiveAccessibilityService.kt` |
| Operate inside any app | taps, types, scrolls, swipes, back, home, recents | `AdaptiveAccessibilityService.kt` |
| Fill forms / type / search in real apps | `ACTION_SET_TEXT` → verify → **clipboard-paste fallback** | `AdaptiveAccessibilityService.fillNode` / `pasteText` |
| Click by element id or ancestor | `ACTION_CLICK` with ancestor walk | `AdaptiveAccessibilityService.clickNode` |
| Find elements by visible text | `findAccessibilityNodeInfosByText` | `AdaptiveAccessibilityService.findByText` |
| Launch any installed app by name/package | label matching + `getLaunchIntentForPackage` | `agent.ts` / `AdaptiveModule.launchApp` |
| Real screen pixels | `MediaProjection` → `VirtualDisplay` → JPEG | `assist/ScreenCapture.kt` |
| Voice input | `SpeechRecognizer`, prefers the offline recognizer | `assist/VoiceInput.kt` |
| Spoken output | `TextToSpeech` | `assist/VoiceInput.kt` |
| **Background listening** | microphone foreground service (`AssistForegroundService`) keeps the process alive; JS re-arms recognition after every turn — works in any foreground app or with the screen off | `AssistForegroundService.kt`, `startAssistLoop` |
| **Voice-answerable confirmations** | when a real "place order?" / "pay?" step needs approval, say *"yes"* / *"do it"* or *"no"* / *"cancel"* by voice | `app/(tabs)/index.tsx` |
| **Selective confirmation** | only genuinely risky actions (pay, order, send, login, delete) confirm; opening apps, tapping, scrolling, and filling forms proceed automatically — this is what makes "open Flipkart and open the cart" complete | `agent.ts` — `HIGH_STAKES_ACTIONS` |
| **Text verification** | fill verifies the field actually took the text; if the app rejected it, it pastes into the focused field | `AdaptiveAccessibilityService.textMatches` / `pasteText` |
| **Any app, full access** | `canPerformGestures` + `canRetrieveWindowContent` + `flagIncludeNotImportantViews` | `res/xml/accessibility_service_config.xml` |

---

## Architecture

```
app/(tabs)/index.tsx      Assistant — hero mic orb, live transcript, voice shortcuts,
                          voice-answerable confirmation dialog, risk-gated confirm logic
app/(tabs)/shopping.tsx   Shopping — goal composer + suggestion chips, "do it again"
app/(tabs)/tools.tsx      Tools — product scan, care-circle (SOS), emergency voice notes
app/(tabs)/screen.tsx     Screen — node tree, element actions, screenshot, "Read aloud"
app/(tabs)/tasks.tsx      Tasks — on-device history
app/(tabs)/settings.tsx   Settings — Gemini key, models, permissions, profile,
                          background-listening, orchestration, saved details

src/native/assist.ts      typed wrapper over the AdaptiveAssist native module + continuous
                          listening loop (startAssistLoop) with failure back-off
src/services/gemini.ts    Gemini Flash client (free tier), retry + 429 handling, key Test
src/services/agent.ts     the plan/act/observe loop, selective confirm, HIGH_STAKES actions
src/services/orchestrator.ts  fused plan → routed execution → verify, with hard timeouts
src/services/engine.ts    Gemini-first router (auto prefers Gemini; local engine has been removed)
src/services/profile.ts   settings + adaptive profile + care contacts + task log
src/ui/                   theme provider + shared components (blind-friendly: spoken live regions)

android/.../assist/
  AdaptiveAccessibilityService.kt   reads and acts on any app (tree, click, scroll, fill/paste, gestures)
  ScreenCapture.kt                  MediaProjection + CaptureService
  AssistForegroundService.kt        microphone-type FGS hosting background sessions
  VoiceInput.kt                     SpeechRecognizer + TextToSpeech
  AdaptiveModule.kt                 the React Native bridge
```

The agent loop gives the model a compressed element list (one line per element with id, class,
text, flags and centre point) rather than raw JSON, so a whole screen fits in one prompt.
Element ids are only valid until the next read — the system prompt states this explicitly.

---

## Build & install

Requires JDK 17, Node 18+, and Android SDK (compileSdk 36 / build-tools 35 / minSdk 24 /
targetSdk 36, set via `expo-build-properties` in `app.json`).

```bash
cd mobile
npm install
npx expo install --check        # verify native module versions match the SDK
```

Signing is driven by `android/keystore.properties` (git-ignored). The shipped APK at
`C:\Users\HP\Desktop\AdaptiveAI-release.apk` is **ARM-only** (`arm64-v8a` + `armeabi-v7a`).

Release build (from `android/`):

```bash
.\gradlew.bat assembleRelease
```

→ `android/app/build/outputs/apk/release/app-release.apk`

For emulator testing only (adds `x86_64`):

```bash
.\gradlew.bat assembleRelease -PincludeEmulatorAbis=true
```

Sign (apksigner, v2 + v3 — correct for minSdk 24):

```cmd
apksigner sign --ks android\app\release.keystore --key-pass pass:<pw> --v2-signing-enabled true --v3-signing-enabled true -out AdaptiveAI-release.apk android\app\build\outputs\apk\release\app-release.apk
```

A release APK embeds the JS bundle; **debug APKs do not** (they bounce to the launcher unless
Metro is serving them).

---

## First run (blind-friendly setup)

1. Install the APK, open AdaptiveAI.
2. **Settings → Accessibility → enable AdaptiveAI.** Without this nothing works — the app cannot
   see or touch other apps.
3. **Settings → Listen in background** — needed for commands in any app (battery cost, opt-in).
4. Grant the microphone permission.
5. On the Assistant tab, tap the mic and speak a task — or type it.

### Verified voice flows (now covered by tests)

- `open flipkart and open cart` — opens Flipkart, navigates to the cart.
- `search mr beast on youtube` — opens YouTube, searches, waits for your confirmation at payment.
- `add apples to the cart` (Zepto/Blinkit) — reads the Zepto page, taps "ADD" per item.
- Short commands work too: `add eggs`, `open cart`, `buy milk`.

---

## Test / verification

```bash
cd mobile && npx tsc --noEmit                                        # typecheck
cd android && .\gradlew.bat assembleRelease                          # native build
```

On-device (emulator or real phone) — see `scripts/test_crossapp.ps1` in this repo for the Android
11 emulator harness that boots a playstore AVD, installs the app, enables the accessibility
service, and drives Chrome/YouTube cross-app.

---

## Fixes & history (recent)

### The Android 11 / Realme XT crash — **root cause found and fixed**
With `compileSdk 36`, Kotlin resolved `List.removeLast()` in `react-native-screens` to the
Java 21 default method that only exists on Android 14+. Result: the app force-closed on the
**first frame draw** on Android 7–13 (`NoSuchMethodError: No interface method removeLast() in
class Ljava/util/List; at ScreenStack.obtainDrawingOp`). Emulator on API 36 never showed it
(the method exists there). Fixed via a `patchNodeModules` Gradle task that rewrites the two
landmine call sites to API-safe equivalents before compilation — deterministic and re-applied
after `npm install`.

### Real-app text filling — **robust + fast**
Rebuilt the fill path: **focus → verify it landed → paste fallback**. Many apps reject
`ACTION_SET_TEXT` (YouTube, Chrome, search boxes); now the text is copied to the clipboard and
pasted into the focused field when needed. Removes the past-a-color false positives.

### Speed
Cut the per-step "settle" waits across the agent loop roughly in half (click 700→300, tap
700→400, swipe 800→500, launch 2200→1600, back 800→450, etc.) so a multi-step voice task moves
snappily without racing the screen's next render.

### Cross-app confirmations — **silent stall fixed**
The old per-click "Tap element 456?" modal froze every delegated task a blind user couldn't
verify, so a task died right after opening an app. Now **only genuinely risky actions** (pay,
place order, send, login, delete, …) confirm; opening apps, tapping, scrolling, and filling
proceed automatically. **Confirmations are voice-answerable**: say *"yes"*/ *"do it"* to approve,
*"no"*/ *"cancel"* to decline.

### Removed APIs / dead code
- On-device llama.cpp (`android/llm/`) and `src/services/nim.ts` / `localLlm.ts` are gone — this
  build is Gemini-Flash-only. (A roger-verify: `find android/llm src/services/nim.ts src/services/localLlm.ts` returns nothing.)

---

## Key design choices & honest gaps

- **Confirmation policy** — As above: confirm only risky actions; blind users delegate, they don't
  rubber-stamp per-tap popups. High-stakes actions confirm *by voice*.
- **Price ceiling** — free-tier Gemini Flash caps throughput; if 429 occurs the app says so.
- **Vendor app behavior varies** — Login challenges, payment confirmations, anti-bot controls on
  IRCTC/BookMyShow/Swiggy still need spoken confirmation or manual completion; AdaptiveAI drives
  the exposed accessibility controls and tells you what it needs.
- **Navigation back** — AdaptiveAI keeps its own stack; "go back" returns within the app, not to
  other apps.
- **Battery** — Background listening is opt-in (microphone foreground service); the app closes
  listeners when background listening is off.

---

## Repository note

This app is a sibling of the 7-service stack in the repo root and is independent of it. The
broken first draft of this mobile app — malformed `app/(tabs/` routes, phantom `zustand` imports —
is preserved in `.attic-mobile-broken-20261101/` for reference.
