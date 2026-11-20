package com.adaptiveai.mobile.assist

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

/** On-device speech recognition and speech synthesis. No server of ours is involved. */
object VoiceInput {

    interface Listener {
        fun onPartial(text: String)
        fun onFinal(text: String)
        fun onError(code: String, message: String)
        fun onSpeechDone(utteranceId: String)
    }

    private val main = Handler(Looper.getMainLooper())
    private var recognizer: SpeechRecognizer? = null
    // Whether the recognizer currently bound was created for the on-device path — the
    // onError retry in start() falls back to the system recognizer only in that case.
    @Volatile
    private var onDeviceRecognizer: Boolean = false

    // Written on the TTS init-callback thread (main) and read/written on the RN bridge thread
    // (speak fast path, stopSpeaking, shutdown) — without @Volatile a stale null read takes the
    // slow path, bumps the generation and orphans the live engine without shutdown().
    @Volatile
    private var tts: TextToSpeech? = null
    private val ttsReady = AtomicBoolean(false)

    // Written on the RN bridge thread (start/shutdown), read on the main thread (STT
    // callbacks) and TTS binder threads — without @Volatile callbacks can observe a stale
    // or null listener and silently drop onFinal/onError events.
    @Volatile
    private var listener: Listener? = null

    fun setListener(l: Listener) { listener = l }

    /**
     * Recognition codes the on-device recognizer can return while the system recognizer
     * serves the same session fine — Samsung (S25-class) returns this class of error via
     * the on-device recognizer (ERROR_CLIENT is the common one). The onError retry in
     * start() falls back to the system path; JS retries the same codes as a second layer.
     */
    private val RETRYABLE_STT_ERRORS = setOf(
        "client", "server", "recognizer_crash", "busy", "unavailable", "audio", "network",
    )

    // Bumped by shutdown() and by every new engine created in speak(); an init callback for
    // a superseded generation releases its own engine instead of resurrecting a dead one.
    private val ttsGeneration = AtomicInteger(0)
    private val listening = AtomicBoolean(false)
    // Bumped on every start()/cancel so callbacks from a superseded recognizer are dropped
    // instead of resolving the current session with a stale outcome.
    private val sessionSeq = AtomicInteger(0)

    /** Whether the recognizer actually created on the last start() was fully offline. */
    @Volatile
    var lastWasOnDevice: Boolean = false
        private set

    /**
     * Capability hint only. The platform exposes no static check for on-device recognition and
     * the only reliable probe — constructing a recognizer — must run on the main thread, which
     * previously saturated it and ANR'd the app before its first frame. The truth is recorded in
     * [lastWasOnDevice] once a real listen has happened.
     */
    fun onDeviceSttAvailable(context: Context): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU

    private fun createRecognizer(context: Context, wantOnDevice: Boolean): SpeechRecognizer {
        val appContext = context.applicationContext
        if (wantOnDevice && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            try {
                val sr = SpeechRecognizer.createOnDeviceSpeechRecognizer(appContext)
                if (sr == null) throw IllegalStateException("No on-device recognizer available")
                lastWasOnDevice = true
                return sr
            } catch (e: Throwable) {
                // No offline recognizer installed; fall through to the system one.
            }
        }
        lastWasOnDevice = false
        // AOSP binds with RecognitionService.SERVICE_INTERFACE and only honours a component
        // given at construction time (createSpeechRecognizer(Context, ComponentName)).
        // Setting the component on the RecognizeSpeech intent is never read by the platform,
        // so the earlier mitigation was dead code. Query the real recognition services,
        // prefer the Google app's (whitelisted in the manifest), and pass it in.
        val component: ComponentName? = runCatching {
            val services = appContext.packageManager.queryIntentServices(
                Intent(android.speech.RecognitionService.SERVICE_INTERFACE),
                0,
            )
            val info = services.firstOrNull {
                it.serviceInfo.packageName == "com.google.android.googlequicksearchbox"
            } ?: services.firstOrNull()
            info?.serviceInfo?.let { ComponentName(it.packageName, it.name) }
        }.getOrNull()
        if (component != null) {
            runCatching { SpeechRecognizer.createSpeechRecognizer(appContext, component) }
                .getOrNull()?.let { return it }
        }
        val sr = SpeechRecognizer.createSpeechRecognizer(appContext)
            ?: throw IllegalStateException("No speech recognizer available on this device")
        return sr
    }

    fun anySttAvailable(context: Context): Boolean =
        runCatching { SpeechRecognizer.isRecognitionAvailable(context) }.getOrDefault(false)

    fun isListening(): Boolean = listening.get()

    @Volatile
    private var sessionActive: Boolean = false

    fun start(context: Context, listener: Listener, language: String, preferOnDevice: Boolean): Boolean {
        this.listener = listener
        sessionActive = true
        // New session id: callbacks from a superseded recognizer are dropped instead of
        // resolving/rejecting the new session with the old session's outcome.
        val session = sessionSeq.incrementAndGet()

        if (!anySttAvailable(context)) {
            listener.onError(
                "unavailable",
                "No speech recognizer installed on this device.",
            )
            return false
        }

        val useOnDevice = preferOnDevice && onDeviceSttAvailable(context)

        fun makeIntent(usedOnDevice: Boolean): Intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(
                RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                RecognizerIntent.LANGUAGE_MODEL_FREE_FORM,
            )
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, language)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, language)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            if (usedOnDevice && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            }
        }

        main.post {
            // Destroy the PREVIOUS recognizer synchronously before building a new one.
            // stopListening() defers destroy by 2s, so a retap used to leave the old
            // client bound while the new one started — ColorOS then hands the new
            // client ERROR_CLIENT (11), which the old client's late callbacks also
            // deliver into this new session.
            recognizer?.let { old ->
                runCatching { old.cancel() }
                runCatching { old.destroy() }
            }
            recognizer = null
            listening.set(false)
            onDeviceRecognizer = false

            if (session != sessionSeq.get()) return@post

            // Binds and starts a recognizer. Returns false when startListening() itself
            // throws — callers decide whether to fall back or surface the error.
            fun startWith(sr: SpeechRecognizer, usedOnDevice: Boolean): Boolean {
                recognizer = sr
                onDeviceRecognizer = usedOnDevice
                sr.setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {
                        if (session != sessionSeq.get()) return
                        listening.set(true)
                    }

                    override fun onBeginningOfSpeech() {}

                    override fun onRmsChanged(rmsdB: Float) {}

                    override fun onBufferReceived(buffer: ByteArray?) {}

                    override fun onEndOfSpeech() {
                        if (session != sessionSeq.get()) return
                        listening.set(false)
                    }

                    override fun onError(error: Int) {
                        if (session != sessionSeq.get()) return
                        listening.set(false)
                        sessionActive = false
                        // Release this client now: a recognizer left bound after its own error
                        // is the zombie that poisons the next start() with a stale code 11.
                        runCatching { sr.destroy() }
                        if (recognizer === sr) recognizer = null
                        val code = errorCode(error)
                        // Samsung/OEM quirk: the on-device recognizer can error (ERROR_CLIENT
                        // is the common one) while the system recognizer serves the same
                        // session fine — retry the session on the system path instead of
                        // failing the user. The JS side retries these codes too; this makes
                        // the retry work on the first attempt already.
                        if (onDeviceRecognizer && code in RETRYABLE_STT_ERRORS) {
                            val sys = runCatching { createRecognizer(context, false) }.getOrNull()
                            if (sys != null && startWith(sys, false)) {
                                sessionActive = true
                                return
                            }
                            sessionActive = false
                        }
                        listener?.onError(code, errorMessage(error))
                    }

                    override fun onResults(results: Bundle?) {
                        if (session != sessionSeq.get()) return
                        listening.set(false)
                        sessionActive = false
                        val text = results
                            ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                            ?.firstOrNull()
                            .orEmpty()
                        runCatching { sr.destroy() }
                        if (recognizer === sr) recognizer = null
                        if (text.isNotBlank()) {
                            listener?.onFinal(text)
                        } else {
                            // Terminal event, or JS waiting on a final result hangs forever.
                            listener?.onError("no_match", "No speech recognized.")
                        }
                    }

                    override fun onPartialResults(partialResults: Bundle?) {
                        if (session != sessionSeq.get()) return
                        val text = partialResults
                            ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                            ?.firstOrNull()
                            .orEmpty()
                        if (text.isNotBlank()) listener?.onPartial(text)
                    }

                    override fun onEvent(eventType: Int, params: Bundle?) {}
                })
                return try {
                    sr.startListening(makeIntent(usedOnDevice))
                    true
                } catch (e: Throwable) {
                    runCatching { sr.destroy() }
                    if (recognizer === sr) recognizer = null
                    false
                }
            }

            val sr = try {
                createRecognizer(context, useOnDevice)
            } catch (e: Throwable) {
                listening.set(false)
                sessionActive = false
                listener?.onError("unavailable", "Could not create a speech recognizer: ${e.message}")
                return@post
            }
            if (!startWith(sr, useOnDevice)) {
                if (useOnDevice) {
                    // Some OEMs throw from startListening() on the on-device recognizer —
                    // fall back to the system recognizer instead of surfacing anything.
                    val sys = runCatching { createRecognizer(context, false) }.getOrNull()
                    if (sys != null && startWith(sys, false)) {
                        return@post
                    }
                }
                listening.set(false)
                sessionActive = false
                listener?.onError("recognizer_crash", "Speech recognizer failed to start.")
            }
        }
        return true
    }

    fun stopListening() {
        listening.set(false)
        sessionActive = false
        main.post {
            recognizer?.let {
                // stopListening() delivers a final onResults/onError — cleanup is delayed
                // so the result lands, then destroy to avoid leaking the native recognizer.
                runCatching { it.stopListening() }
                val old = it
                main.postDelayed({
                    runCatching { old.destroy() }
                }, 2000)
            }
            recognizer = null
        }
    }

    fun cancelListening() {
        // Use sessionActive (set in start(), cleared on terminal callback) so a cancel
        // during recognizer-init still emits cancelled and JS never hangs.
        val wasActive = sessionActive
        sessionActive = false
        listening.set(false)
        // Invalidate callbacks still queued from the recognizer we are about to kill —
        // the comment above promises cancel() bumps the sequence too, and without it a
        // cancelled session could still deliver a ghost onFinal/onError to the loop.
        sessionSeq.incrementAndGet()
        main.post {
            if (wasActive) listener?.onError("cancelled", "Voice input cancelled.")
            recognizer?.let {
                runCatching { it.cancel() }
                runCatching { it.destroy() }
            }
            recognizer = null
        }
    }

    fun speak(context: Context, text: String, rate: Float, language: String, utteranceId: String, attempt: Int = 0) {
        val existing = tts
        if (existing != null && ttsReady.get()) {
            // The engine is reused across calls whose language may have changed — apply the
            // requested locale on every utterance (emit() does it on the main thread), not
            // only once at engine init.
            emit(existing, text, rate, language, utteranceId)
            return
        }
        ttsReady.set(false)

        // OnInitListener.onInit takes only a status. The engine is handed back through an
        // AtomicReference so the callback (which runs on the main thread) reads a correctly
        // published value rather than a field that may not be visible yet. Each attempt gets
        // its own generation: a second rapid speak() or shutdown() bumps it, and a stale
        // callback shuts its engine down instead of overwriting the newer one or leaking it.
        val generation = ttsGeneration.incrementAndGet()
        // Replace, never stack: at this point `tts` is either null or an engine that never
        // reached ready (init still in flight, or an OEM TTS service that never calls
        // onInit). Leaving it in place would hold one dead TTS connection per speak() for
        // the life of the process. Generation is already bumped, so if its callback is
        // still pending it takes the superseded path below and shuts down again safely.
        tts?.let { stale -> runCatching { stale.shutdown() } }
        tts = null
        val holder = AtomicReference<TextToSpeech?>(null)
        val engine = TextToSpeech(context.applicationContext) { status ->
            if (generation != ttsGeneration.get()) {
                // Superseded by a newer speak() or by shutdown() while init was in flight —
                // release this orphaned engine; emit terminal event so JS awaiting the
                // superseded utterance does not hang forever.
                main.post { listener?.onSpeechDone(utteranceId) }
                holder.get()?.let { orphaned ->
                    runCatching { orphaned.shutdown() }
                    // tts may still point at this engine from the eager assignment in
                    // speak(); clear it so stopSpeaking()/shutdown() do not resurrect a
                    // released engine.
                    if (tts === orphaned) {
                        tts = null
                        ttsReady.set(false)
                    }
                }
                return@TextToSpeech
            }
            if (status == TextToSpeech.SUCCESS) {
                val created = holder.get()
                if (created != null) {
                    created.language = Locale.forLanguageTag(language)
                    created.setOnUtteranceProgressListener(progressListener)
                    applySpeechAttributes(created)
                    tts = created
                    ttsReady.set(true)
                    emit(created, text, rate, language, utteranceId)
                } else {
                    listener?.onError("tts", "Text-to-speech engine was not available")
                }
            } else {
                // Init failed: the engine is dead, shut it down instead of leaving it in tts.
                val dead = holder.get()
                if (dead != null) runCatching { dead.shutdown() }
                if (tts === dead) tts = null
                ttsReady.set(false)
                // Some OEM TTS services (Samsung among them) report init failure but become
                // usable a moment later — retry instead of permanently going silent. The
                // generation check keeps a newer speak()/shutdown() from resurrecting this
                // one after the retry fires.
                if (generation == ttsGeneration.get() && attempt < 2) {
                    main.postDelayed({
                        if (generation == ttsGeneration.get()) {
                            speak(context, text, rate, language, utteranceId, attempt + 1)
                        }
                    }, 500)
                } else {
                    listener?.onError("tts_init", "Text-to-speech failed to initialise (status $status)")
                }
            }
        }
        holder.set(engine)
        tts = engine
    }

    private fun applySpeechAttributes(engine: TextToSpeech) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return
        try {
            engine.setAudioAttributes(
                android.media.AudioAttributes.Builder()
                    .setUsage(android.media.AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build(),
            )
        } catch (e: Throwable) {
            // Some OEM TTS services reject attribute combos — speech must keep working.
        }
    }

    private val progressListener = object : UtteranceProgressListener() {
        override fun onStart(id: String?) {}

        override fun onDone(id: String?) {
            main.post { id?.let { listener?.onSpeechDone(it) } }
        }

        override fun onStop(id: String?, interrupted: Boolean) {
            // QUEUE_FLUSH, stopSpeaking() and a superseded engine land here instead of onDone
            // (API 23+; minSdk is 24) — still a terminal event for that utterance, or anything
            // awaiting onSpeakDone hangs.
            main.post { id?.let { listener?.onSpeechDone(it) } }
        }

        @Deprecated("Deprecated in the platform API")
        override fun onError(id: String?) {
            main.post {
                listener?.onError("tts", "Speech playback failed")
                // Terminal event for that utterance, or JS awaiting its onSpeakDone hangs.
                id?.let { listener?.onSpeechDone(it) }
            }
        }
    }

    private fun emit(engine: TextToSpeech, text: String, rate: Float, language: String, utteranceId: String) {
        if (text.isBlank()) {
            listener?.onError("tts", "Nothing to speak.")
            listener?.onSpeechDone(utteranceId)
            return
        }
        main.post {
            // Re-apply the locale per utterance so a language change is honoured without
            // recreating the engine. OEM TTS engines vary: some lack the full locale
            // ("en-US") but have the base language ("en") or the system default — fall
            // back rather than going silent when the requested one is missing.
            var localeResult = runCatching { engine.language = Locale.forLanguageTag(language) }
                .getOrDefault(TextToSpeech.LANG_MISSING_DATA)
            if (localeResult != TextToSpeech.SUCCESS && language.contains('-')) {
                localeResult = runCatching { engine.language = Locale(language.substringBefore('-')) }
                    .getOrDefault(TextToSpeech.LANG_MISSING_DATA)
            }
            if (localeResult != TextToSpeech.SUCCESS) {
                localeResult = runCatching { engine.language = Locale.getDefault() }
                    .getOrDefault(TextToSpeech.LANG_MISSING_DATA)
            }
            if (localeResult != TextToSpeech.SUCCESS) {
                listener?.onError("tts", "Speech language data is missing on this device.")
                listener?.onSpeechDone(utteranceId)
            } else {
                engine.setSpeechRate(rate.coerceIn(0.25f, 4f))
                val result = runCatching {
                    engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, utteranceId)
                }.getOrDefault(TextToSpeech.ERROR)
                if (result != TextToSpeech.SUCCESS) {
                    listener?.onError("tts", "Speech playback was rejected by the device (status $result).")
                    listener?.onSpeechDone(utteranceId)
                }
            }
        }
    }

    fun stopSpeaking() {
        tts?.let { runCatching { it.stop() } }
    }

    fun shutdown() {
        // Invalidate any init callback still in flight first: it will then release its own
        // engine instead of reassigning tts after we have torn everything down.
        ttsGeneration.incrementAndGet()
        cancelListening()
        stopSpeaking()
        tts?.let { runCatching { it.shutdown() } }
        tts = null
        ttsReady.set(false)
        listener = null
    }

    private fun errorCode(error: Int): String = when (error) {
        SpeechRecognizer.ERROR_NO_MATCH -> "no_match"
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "timeout"
        SpeechRecognizer.ERROR_AUDIO -> "audio"
        SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "network"
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "permissions"
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "busy"
        SpeechRecognizer.ERROR_CLIENT -> "client"
        SpeechRecognizer.ERROR_SERVER -> "server"
        else -> "unknown"
    }

    private fun errorMessage(error: Int): String = when (error) {
        SpeechRecognizer.ERROR_NO_MATCH -> "Didn't catch that. Try again."
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "No speech detected."
        SpeechRecognizer.ERROR_AUDIO -> "Microphone error."
        SpeechRecognizer.ERROR_NETWORK -> "Speech recognition needs a network connection or an offline language pack."
        SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "Speech recognition timed out."
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Microphone permission was denied."
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Recognizer is busy."
        SpeechRecognizer.ERROR_CLIENT ->
            "Speech service not available. Install or update the Google app, or try a different speech engine in Settings."
        SpeechRecognizer.ERROR_SERVER -> "Recognizer server error."
        else -> "Speech recognition failed (code $error)."
    }
}


