package com.adaptiveai.mobile.assist

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.media.projection.MediaProjectionConfig
import android.net.Uri
import android.os.Build
import android.provider.Settings
import com.facebook.react.bridge.ActivityEventListener
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.LifecycleEventListener
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.bridge.WritableMap
import com.facebook.react.modules.core.DeviceEventManagerModule
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.vision.objectdetector.ObjectDetector
import com.google.mediapipe.tasks.vision.objectdetector.ObjectDetector.ObjectDetectorOptions
import com.google.mediapipe.tasks.vision.core.RunningMode
import org.json.JSONArray
import org.json.JSONObject

class AdaptiveModule(private val reactContext: ReactApplicationContext) :
    ReactContextBaseJavaModule(reactContext), ActivityEventListener, LifecycleEventListener {

    init {
        reactContext.addActivityEventListener(this)
        reactContext.addLifecycleEventListener(this)
    }

    override fun getName(): String = MODULE_NAME

    // Required by NativeEventEmitter on the old architecture; events are emitted via
    // RCTDeviceEventEmitter so these are intentionally empty.
    @ReactMethod
    fun addListener(eventName: String?) {}

    @ReactMethod
    fun removeListeners(count: Int?) {}

    // requestScreenCapture runs on the NativeModules thread while onActivityResult and the
    // onHostDestroy path run on the main thread — every access must hold this lock, or a
    // second consent request can end up settled by the FIRST dialog's result.
    private val capturePromiseLock = Any()
    private var pendingCapturePromise: Promise? = null

    // region status & permissions

    @ReactMethod
    fun getStatus(promise: Promise) {
        try {
            val ctx = reactContext
            val map = Arguments.createMap().apply {
                putBoolean("accessibilityEnabled", AdaptiveAccessibilityService.isRunning())
                putBoolean("sttAvailable", VoiceInput.anySttAvailable(ctx))
                putBoolean("onDeviceStt", VoiceInput.onDeviceSttAvailable(ctx))
                putBoolean("lastListenOnDevice", VoiceInput.lastWasOnDevice)
                putBoolean("listening", VoiceInput.isListening())
                putBoolean("captureActive", ScreenCapture.isActive())
                putBoolean("assistSession", AssistForegroundService.isRunning())
                putString("foregroundApp", AdaptiveAccessibilityService.foregroundPackage ?: "")
                putInt("sdkInt", Build.VERSION.SDK_INT)
            }
            promise.resolve(map)
        } catch (e: Throwable) {
            promise.reject("status_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    @ReactMethod
    fun openAccessibilitySettings(promise: Promise) {
        try {
            val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            reactContext.startActivity(intent)
            promise.resolve(true)
        } catch (e: Throwable) {
            promise.reject("open_settings_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    @ReactMethod
    fun openAppSettings(promise: Promise) {
        try {
            val intent = Intent(
                Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.fromParts("package", reactContext.packageName, null),
            ).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
            reactContext.startActivity(intent)
            promise.resolve(true)
        } catch (e: Throwable) {
            promise.reject("open_settings_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    // endregion

    // region screen reading & acting

    @ReactMethod
    fun readScreen(limit: Int, promise: Promise) {
        try {
            val tree = AdaptiveAccessibilityService.captureTree(if (limit > 0) limit else 500)
            promise.resolve(tree.toString())
        } catch (e: Throwable) {
            promise.reject("read_screen_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    @ReactMethod
    fun findByText(query: String, promise: Promise) {
        try {
            promise.resolve(AdaptiveAccessibilityService.findByText(query).toString())
        } catch (e: Throwable) {
            promise.reject("find_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    @ReactMethod
    fun fillNode(id: Int, value: String, promise: Promise) {
        // Runs on a worker thread, never the bridge thread: filling a real app field now
        // settles (sleeps) briefly between focus and paste so the target app has time to
        // register focus, and the clipboard IPC can block. Park it off-thread so getStatus/
        // voice/capture are not stalled behind every keystroke — same reason click/tap below
        // are threaded.
        Thread {
            try {
                promise.resolve(AdaptiveAccessibilityService.fillNode(id, value).toString())
            } catch (e: Throwable) {
                promise.reject("fill_failed", e.message ?: e.javaClass.simpleName, e)
            }
        }.start()
    }

    // clickNode/scrollNode fall back to dispatchGesture, which parks a latch for up to 3s.
    // They used to run synchronously on the bridge thread, stalling getStatus/voice/capture
    // behind every text tap — same reason tap() below is off-thread.
    @ReactMethod
    fun clickNode(id: Int, promise: Promise) {
        Thread {
            try {
                promise.resolve(AdaptiveAccessibilityService.clickNode(id))
            } catch (e: Throwable) {
                promise.reject("click_failed", e.message ?: e.javaClass.simpleName, e)
            }
        }.start()
    }

    @ReactMethod
    fun scrollNode(id: Int, forward: Boolean, promise: Promise) {
        Thread {
            try {
                promise.resolve(AdaptiveAccessibilityService.scrollNode(id, forward))
            } catch (e: Throwable) {
                promise.reject("scroll_failed", e.message ?: e.javaClass.simpleName, e)
            }
        }.start()
    }

    // Gestures park a latch up to 3s — run them off the RN bridge thread so getStatus/
    // voice/capture are not stalled behind every tap.
    @ReactMethod
    fun tap(x: Double, y: Double, promise: Promise) {
        Thread {
            try {
                promise.resolve(AdaptiveAccessibilityService.tap(x.toFloat(), y.toFloat()))
            } catch (e: Throwable) {
                promise.reject("tap_failed", e.message ?: e.javaClass.simpleName, e)
            }
        }.start()
    }

    @ReactMethod
    fun longPress(x: Double, y: Double, promise: Promise) {
        Thread {
            try {
                promise.resolve(AdaptiveAccessibilityService.longPress(x.toFloat(), y.toFloat()))
            } catch (e: Throwable) {
                promise.reject("long_press_failed", e.message ?: e.javaClass.simpleName, e)
            }
        }.start()
    }

    @ReactMethod
    fun swipe(x1: Double, y1: Double, x2: Double, y2: Double, durationMs: Int, promise: Promise) {
        Thread {
            try {
                val ok = AdaptiveAccessibilityService.swipe(
                    x1.toFloat(),
                    y1.toFloat(),
                    x2.toFloat(),
                    y2.toFloat(),
                    durationMs.coerceIn(50, 1500).toLong().takeIf { durationMs > 0 } ?: 320L,
                )
                promise.resolve(ok)
            } catch (e: Throwable) {
                promise.reject("swipe_failed", e.message ?: e.javaClass.simpleName, e)
            }
        }.start()
    }

    @ReactMethod
    fun globalAction(action: String, promise: Promise) {
        try {
            val ok = when (action.lowercase()) {
                "back" -> AdaptiveAccessibilityService.goBack()
                "home" -> AdaptiveAccessibilityService.goHome()
                "recents" -> AdaptiveAccessibilityService.openRecents()
                "notifications" -> AdaptiveAccessibilityService.openNotifications()
                else -> throw IllegalArgumentException("Unknown global action: $action")
            }
            promise.resolve(ok)
        } catch (e: Throwable) {
            promise.reject("global_action_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    // endregion

    // region apps

    @ReactMethod
    fun launchApp(packageName: String, promise: Promise) {
        try {
            val intent = reactContext.packageManager.getLaunchIntentForPackage(packageName)
                ?: throw ActivityNotFoundException("No launchable app with package $packageName")
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            reactContext.startActivity(intent)
            promise.resolve(true)
        } catch (e: Throwable) {
            promise.reject("launch_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    @ReactMethod
    fun openUrl(url: String, promise: Promise) {
        try {
            val uri = Uri.parse(url)
            // Allowlist: model-initiated intents must not open tel:/sms:/market:/intent: etc.
            if (uri.scheme !in listOf("http", "https")) {
                promise.reject("open_url_blocked", "Only http/https URLs can be opened")
                return
            }
            val intent = Intent(Intent.ACTION_VIEW, uri).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            reactContext.startActivity(intent)
            promise.resolve(true)
        } catch (e: Throwable) {
            promise.reject("open_url_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    @ReactMethod
    fun listApps(promise: Promise) {
        try {
            val pm = reactContext.packageManager
            val intent = Intent(Intent.ACTION_MAIN, null).addCategory(Intent.CATEGORY_LAUNCHER)
            val resolved = pm.queryIntentActivities(intent, 0)
            val seen = HashSet<String>()
            val array = Arguments.createArray()
            for (info in resolved) {
                val pkg = info.activityInfo.packageName
                if (pkg == reactContext.packageName || !seen.add(pkg)) continue
                val label = try {
                    info.activityInfo.loadLabel(pm)?.toString() ?: pkg
                } catch (e: Throwable) {
                    pkg
                }
                array.pushMap(Arguments.createMap().apply {
                    putString("package", pkg)
                    putString("label", label)
                })
            }
            promise.resolve(array)
        } catch (e: Throwable) {
            promise.reject("list_apps_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    // endregion

    // region screen capture

    @ReactMethod
    fun requestScreenCapture(promise: Promise) {
        val activity: Activity? = currentActivity
        if (activity == null) {
            promise.reject("no_activity", "No foreground activity to request capture from")
            return
        }
        if (ScreenCapture.isActive()) {
            promise.resolve(true)
            return
        }
        synchronized(capturePromiseLock) {
            if (pendingCapturePromise != null) {
                // A consent dialog is already up. Rejecting the old one and storing a second
                // promise lets the FIRST dialog's onActivityResult settle the SECOND request;
                // refuse the new request instead.
                promise.reject("request_in_flight", "A screen capture consent dialog is already showing")
                return
            }
            pendingCapturePromise = promise
        }
        try {
            val mpm = reactContext.getSystemService(Context.MEDIA_PROJECTION_SERVICE)
                as MediaProjectionManager
            val captureIntent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                mpm.createScreenCaptureIntent(
                    MediaProjectionConfig.createConfigForDefaultDisplay(),
                )
            } else {
                mpm.createScreenCaptureIntent()
            }
            activity.startActivityForResult(captureIntent, REQUEST_CAPTURE)
        } catch (e: Throwable) {
            synchronized(capturePromiseLock) { pendingCapturePromise = null }
            promise.reject("capture_request_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    @ReactMethod
    fun captureScreen(quality: Int, promise: Promise) {
        try {
            if (!ScreenCapture.isActive()) {
                promise.reject("capture_inactive", "Screen capture has not been started yet")
                return
            }
            // captureFrame polls up to ~1s for the first frame — never sleep on the shared
            // NativeModules thread or every other native call stalls behind it.
            Thread {
                try {
                    val base64 = ScreenCapture.captureFrame(quality)
                    if (base64 == null) {
                        promise.reject("no_frame", "No frame was available; the screen may be off or secured")
                    } else {
                        promise.resolve(base64)
                    }
                } catch (e: Throwable) {
                    promise.reject("capture_failed", e.message ?: e.javaClass.simpleName, e)
                }
            }.start()
        } catch (e: Throwable) {
            promise.reject("capture_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    @ReactMethod
    fun shareScreen(quality: Int, promise: Promise) {
        try {
            // saveFrame delegates to captureFrame's ~1s polling loop — keep it off the shared
            // NativeModules thread too.
            Thread {
                try {
                    val uri = ScreenCapture.saveFrame(reactContext, quality.coerceIn(20, 95))
                        ?: throw IllegalStateException("No screen frame is available. Start screen capture first.")
                    val send = Intent(Intent.ACTION_SEND).apply {
                        type = "image/jpeg"
                        putExtra(Intent.EXTRA_STREAM, uri)
                        clipData = ClipData.newRawUri("AdaptiveAI screen", uri)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    val chooser = Intent.createChooser(send, "Share captured screen").apply {
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        // The grant must survive the chooser hop to the final target app,
                        // otherwise the screenshot URI throws SecurityException on many OEMs.
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        clipData = send.clipData
                    }
                    reactContext.startActivity(chooser)
                    promise.resolve(true)
                } catch (e: Throwable) {
                    promise.reject("share_screen_failed", e.message ?: e.javaClass.simpleName, e)
                }
            }.start()
        } catch (e: Throwable) {
            promise.reject("share_screen_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    @ReactMethod
    fun stopScreenCapture(promise: Promise) {
        try {
            CaptureService.stop(reactContext)
            ScreenCapture.release()
            promise.resolve(true)
        } catch (e: Throwable) {
            promise.reject("capture_stop_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    /**
     * On-device OCR of the current screen via Google ML Kit (free, no API key).
     * Requires an active screen-capture session. Resolves with the recognised text
     * (may be empty) — empty is not an error, it means no text was found in pixels.
     */
    @ReactMethod
    fun ocrScreen(quality: Int, promise: Promise) {
        if (!ScreenCapture.isActive()) {
            promise.reject("capture_inactive", "Screen capture has not been started yet")
            return
        }
        Thread {
            try {
                val b64 = ScreenCapture.captureFrame(quality.coerceIn(20, 95))
                    ?: throw IllegalStateException("No screen frame is available.")
                val bytes = android.util.Base64.decode(b64, android.util.Base64.NO_WRAP)
                val bitmap = try {
                    android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                } catch (e: Throwable) {
                    null
                } ?: throw IllegalStateException("Could not decode the captured frame.")
                val image = InputImage.fromBitmap(bitmap, 0)
                val recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
                recognizer.process(image)
                    .addOnSuccessListener { result ->
                        // These listeners run on the MAIN thread with no surrounding try —
                        // a Throwable from close()/recycle() would be an uncaught
                        // main-thread exception and kill the process. Settle once, safely.
                        try {
                            promise.resolve(result.text)
                        } catch (t: Throwable) {
                            // Promise already settled by a racing path; never rethrow on main.
                        } finally {
                            runCatching { recognizer.close() }
                            runCatching { bitmap.recycle() }
                        }
                    }
                    .addOnFailureListener { err ->
                        try {
                            promise.reject("ocr_failed", err.message ?: "OCR failed", err)
                        } catch (t: Throwable) {
                            // Already settled — ignore.
                        } finally {
                            runCatching { recognizer.close() }
                            runCatching { bitmap.recycle() }
                        }
                    }
            } catch (e: Throwable) {
                promise.reject("ocr_failed", e.message ?: e.javaClass.simpleName, e)
            }
        }.start()
    }

    /** MediaPipe object detection over the captured frame. Returns JSON array of {label, score, cx, cy}. */
    @ReactMethod
    fun detectObjects(quality: Int, promise: Promise) {
        if (!ScreenCapture.isActive()) {
            promise.reject("capture_inactive", "Screen capture has not been started yet")
            return
        }
        Thread {
            var payload: String? = null
            try {
                val b64 = ScreenCapture.captureFrame(quality.coerceIn(20, 95))
                    ?: throw IllegalStateException("No screen frame is available.")
                val bytes = android.util.Base64.decode(b64, android.util.Base64.NO_WRAP)
                val bitmap = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    ?: throw IllegalStateException("Could not decode the captured frame.")
                try {
                    val baseOptions = BaseOptions.builder()
                        .setModelAssetPath("efficientdet_lite0.tflite")
                        .build()
                    val options = ObjectDetectorOptions.builder()
                        .setBaseOptions(baseOptions)
                        .setMaxResults(10)
                        .setScoreThreshold(0.3f)
                        .setRunningMode(RunningMode.IMAGE)
                        .build()
                    val detector = ObjectDetector.createFromOptions(reactContext, options)
                    try {
                        val mpImage = BitmapImageBuilder(bitmap).build()
                        try {
                            val result = detector.detect(mpImage)
                            // Scale thumbnail coords to full-screen pixels: capture is ≤1024
                            // on the long edge, taps need real screen pixels.
                            val metrics = reactContext.resources.displayMetrics
                            val bmW = bitmap.width.coerceAtLeast(1)
                            val bmH = bitmap.height.coerceAtLeast(1)
                            val scaleX = metrics.widthPixels.toDouble() / bmW
                            val scaleY = metrics.heightPixels.toDouble() / bmH
                            val arr = JSONArray()
                            result.detections().forEach { det ->
                                val cat = det.categories().maxByOrNull { it.score() }
                                if (cat != null) {
                                    val bb = det.boundingBox()
                                    arr.put(JSONObject().apply {
                                        put("label", cat.categoryName())
                                        put("score", cat.score().toDouble())
                                        put("cx", bb.centerX() * scaleX)
                                        put("cy", bb.centerY() * scaleY)
                                    })
                                }
                            }
                            // Store only: the finallys below must run BEFORE the promise is
                            // settled. Resolving first meant a teardown Throwable landed in
                            // the catch and rejected an already-resolved promise — RN throws
                            // on a second settle, inside this raw thread, which kills the
                            // process on Android.
                            payload = arr.toString()
                        } finally {
                            mpImage.close()
                        }
                    } finally {
                        detector.close()
                    }
                } finally {
                    bitmap.recycle()
                }
            } catch (e: Throwable) {
                // UnsatisfiedLinkError / OutOfMemoryError are Errors, not Exceptions — on
                // 32-bit devices or low-RAM phones MediaPipe must reject, never crash.
                promise.reject(
                    "detect_unavailable",
                    "Object detection unavailable: ${e.message ?: e.javaClass.simpleName}",
                    e,
                )
                return@Thread
            }
            payload?.let { promise.resolve(it) }
        }.start()
    }

    override fun onActivityResult(activity: Activity?, requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != REQUEST_CAPTURE) return
        val promise = synchronized(capturePromiseLock) {
            val p = pendingCapturePromise
            pendingCapturePromise = null
            p
        } ?: return

        if (resultCode != Activity.RESULT_OK || data == null) {
            promise.reject("capture_denied", "Screen capture permission was not granted")
            return
        }

        try {
            ScreenCapture.ensureChannel(reactContext)
            CaptureService.start(reactContext, resultCode, data)
        } catch (e: Throwable) {
            promise.reject("capture_start_failed", "Screen capture could not start: ${e.message}", e)
            return
        }
        // The service creates the projection once it is foregrounded. Poll off the main
        // thread: onActivityResult is delivered on main and sleeping there ANRs the app.
        Thread {
            val deadline = System.currentTimeMillis() + 2500
            while (System.currentTimeMillis() < deadline && !ScreenCapture.isActive()) {
                try {
                    Thread.sleep(50)
                } catch (e: InterruptedException) {
                    Thread.currentThread().interrupt()
                    break
                }
            }
            if (ScreenCapture.isActive()) {
                promise.resolve(true)
            } else {
                promise.reject("capture_start_failed", "Screen capture session could not be started")
            }
        }.start()
    }

    override fun onNewIntent(intent: Intent?) {}

    // endregion

    // region LifecycleEventListener

    override fun onHostResume() {}

    override fun onHostPause() {}

    override fun onHostDestroy() {
        // onActivityResult may never arrive if the activity went away while the system
        // consent dialog was up — settle the promise so the JS await does not hang, and
        // make a late onActivityResult a no-op (pendingCapturePromise is null).
        val promise = synchronized(capturePromiseLock) {
            val p = pendingCapturePromise
            pendingCapturePromise = null
            p
        }
        promise?.reject("host_destroyed", "Activity went away before capture consent result")
    }

    // endregion

    // region assist session (background voice host)

    /** Starts the microphone foreground service so listening survives backgrounding. */
    @ReactMethod
    fun startAssistSession(promise: Promise) {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M &&
                reactContext.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) !=
                android.content.pm.PackageManager.PERMISSION_GRANTED
            ) {
                promise.reject("permissions", "Microphone permission has not been granted")
                return
            }
            AssistForegroundService.start(reactContext)
            // startForegroundService is async: on Android 12+ the promotion may still fail
            // later, so resolve with the actual running state instead of blindly true.
            // Poll briefly off the bridge thread, then report honestly.
            Thread {
                val deadline = System.currentTimeMillis() + 1500
                while (System.currentTimeMillis() < deadline && !AssistForegroundService.isRunning()) {
                    try {
                        Thread.sleep(50)
                    } catch (e: InterruptedException) {
                        Thread.currentThread().interrupt()
                        break
                    }
                }
                promise.resolve(AssistForegroundService.isRunning())
            }.start()
        } catch (e: Throwable) {
            promise.reject("assist_session_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    @ReactMethod
    fun stopAssistSession(promise: Promise) {
        try {
            AssistForegroundService.stop(reactContext)
            promise.resolve(true)
        } catch (e: Throwable) {
            promise.reject("assist_session_stop_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    // endregion

    // region voice

    @ReactMethod
    fun startVoice(language: String, preferOnDevice: Boolean, promise: Promise) {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M &&
                reactContext.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) !=
                android.content.pm.PackageManager.PERMISSION_GRANTED
            ) {
                promise.reject("permissions", "Microphone permission has not been granted")
                return
            }
            val started = VoiceInput.start(
                reactContext,
                eventListener,
                language.ifBlank { "en-US" },
                preferOnDevice,
            )
            promise.resolve(started)
        } catch (e: Throwable) {
            promise.reject("voice_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    @ReactMethod
    fun stopVoice(promise: Promise) {
        try {
            VoiceInput.stopListening()
            promise.resolve(true)
        } catch (e: Throwable) {
            promise.reject("voice_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    @ReactMethod
    fun cancelVoice(promise: Promise) {
        try {
            VoiceInput.cancelListening()
            promise.resolve(true)
        } catch (e: Throwable) {
            promise.reject("voice_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    @ReactMethod
    fun speak(text: String, rate: Double, language: String, promise: Promise) {
        try {
            val id = "u" + System.nanoTime()
            // Register listener so completion fires even when speak() is called before startVoice().
            VoiceInput.setListener(eventListener)
            VoiceInput.speak(reactContext, text, rate.toFloat(), language.ifBlank { "en-US" }, id)
            promise.resolve(id)
        } catch (e: Throwable) {
            promise.reject("speak_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    @ReactMethod
    fun stopSpeaking(promise: Promise) {
        try {
            VoiceInput.stopSpeaking()
            promise.resolve(true)
        } catch (e: Throwable) {
            promise.reject("speak_failed", e.message ?: e.javaClass.simpleName, e)
        }
    }

    private val eventListener = object : VoiceInput.Listener {
        override fun onPartial(text: String) {
            emit("onVoicePartial", Arguments.createMap().apply { putString("text", text) })
        }

        override fun onFinal(text: String) {
            emit("onVoiceFinal", Arguments.createMap().apply { putString("text", text) })
        }

        override fun onError(code: String, message: String) {
            emit(
                "onVoiceError",
                Arguments.createMap().apply {
                    putString("code", code)
                    putString("message", message)
                },
            )
        }

        override fun onSpeechDone(utteranceId: String) {
            emit("onSpeakDone", Arguments.createMap().apply { putString("utteranceId", utteranceId) })
        }
    }

    private fun emit(eventName: String, payload: WritableMap) {
        if (!reactContext.hasActiveCatalystInstance()) return
        reactContext
            .getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
            .emit(eventName, payload)
    }

    override fun onCatalystInstanceDestroy() {
        super.onCatalystInstanceDestroy()
        // Unregister first: a reloaded catalyst would otherwise leave this dead module
        // (holding reactContext) reachable from the listener lists forever.
        runCatching { reactContext.removeActivityEventListener(this) }
        runCatching { reactContext.removeLifecycleEventListener(this) }
        VoiceInput.shutdown()
        ScreenCapture.release()
        // Without this the CaptureService FGS keeps the MediaProjection alive after JS is
        // dead — an orphaned privacy capture until tap-to-stop or reboot.
        CaptureService.stop(reactContext)
    }

    // endregion

    companion object {
        const val MODULE_NAME = "AdaptiveAssist"
        private const val REQUEST_CAPTURE = 8613
    }
}


