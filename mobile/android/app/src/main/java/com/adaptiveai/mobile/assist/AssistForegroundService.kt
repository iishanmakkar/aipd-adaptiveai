package com.adaptiveai.mobile.assist

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import com.adaptiveai.mobile.R

/**
 * Hosts an assist session so voice listening and agent runs survive the app being
 * backgrounded or the screen turning off. The service itself owns no audio: it keeps the
 * process alive with a microphone-type foreground-service notification and a partial wake
 * lock, while the actual SpeechRecognizer sessions are still driven through VoiceInput from
 * the RN bridge (the JS side re-arms recognition after every final/error, which is what
 * makes listening continuous).
 *
 * Starting a microphone-type FGS is only allowed while the app is in the foreground, which
 * holds here — the toggle lives in the Assistant/Settings UI.
 */
class AssistForegroundService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        // running is set only after startForeground succeeds in onStartCommand —
        // setting it here would report assistSession:true before promotion.
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        ensureChannel(this)
        val promoted = try {
            // FOREGROUND_SERVICE_TYPE_MICROPHONE only exists from Android 11 (API 30).
            // Passing its value on Android 10 throws IllegalArgumentException and kills
            // the process, so the type is only set from R onwards.
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                startForeground(
                    NOTIFICATION_ID,
                    buildNotification(this),
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE,
                )
            } else {
                startForeground(NOTIFICATION_ID, buildNotification(this))
            }
            true
        } catch (e: Throwable) {
            // A system restart after the process was killed re-runs onStartCommand with a null
            // intent — that is a background start, and a microphone-type FGS cannot be promoted
            // from the background on Android 14+ (ForegroundServiceStartNotAllowedException /
            // SecurityException). That used to crash the process.
            //
            // startForegroundService() was still called, so satisfy the 5-second promotion
            // contract with an untyped startForeground before giving up — stopping without
            // ever promoting is what throws RemoteServiceException and force-closes the app.
            runCatching { startForeground(NOTIFICATION_ID, buildNotification(this)) }
            false
        }
        if (!promoted) {
            running = false
            // Background restart (system killed the process): a microphone FGS cannot be
            // promoted from the background, so stop quietly — non-sticky for this path to
            // avoid a restart loop. The JS watchdog restarts the session when the app next
            // comes to the foreground.
            stopSelf()
            return START_NOT_STICKY
        }
        running = true
        acquireWakeLock()
        // Sticky while healthy: if the system kills the process, the service is recreated.
        // On the recreate, startForeground is guarded above and stops quietly if it cannot
        // be promoted from the background, so this can never crash the process again.
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        releaseWakeLock()
        super.onDestroy()
    }

    private fun acquireWakeLock() {
        if (wakeLock?.isHeld == true) return
        // A missing WAKE_LOCK permission must never crash the service — the SecurityException
        // would propagate out of startForegroundService and kill the whole app process.
        runCatching {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "adaptiveai:assist-session").apply {
                setReferenceCounted(false)
                // No timeout: the session is user-controlled (Settings toggle + notification),
                // and dropping the lock early is exactly what let listening die with the
                // screen off. The FGS notification is the visible indicator of the cost.
                acquire()
            }
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.let { runCatching { if (it.isHeld) it.release() } }
        wakeLock = null
    }

    companion object {
        const val CHANNEL_ID = "adaptiveai_assist_session"
        const val NOTIFICATION_ID = 4712
        const val ACTION_STOP = "com.adaptiveai.mobile.assist.ASSIST_STOP"

        @Volatile
        private var running = false

        @Volatile
        private var wakeLock: PowerManager.WakeLock? = null

        fun isRunning(): Boolean = running

        fun start(context: Context) {
            val intent = Intent(context, AssistForegroundService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            // stopService() is exempt from background-start restrictions — a stop
            // INTENT delivered via startService would throw from the background
            // while the service is live, leaking it forever.
            try {
                val intent = Intent(context, AssistForegroundService::class.java).apply {
                    action = ACTION_STOP
                }
                context.stopService(intent)
            } catch (e: Throwable) {
                // Already gone — exactly what stop wants.
            }
        }

        fun ensureChannel(context: Context) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            if (nm.getNotificationChannel(CHANNEL_ID) != null) return
            nm.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    context.getString(R.string.assist_channel_name),
                    NotificationManager.IMPORTANCE_LOW,
                ).apply {
                    description = context.getString(R.string.assist_channel_desc)
                    setShowBadge(false)
                },
            )
        }

        fun buildNotification(context: Context): Notification {
            val tap = context.packageManager.getLaunchIntentForPackage(context.packageName)
                ?: Intent(context, com.adaptiveai.mobile.MainActivity::class.java)
            val pending = PendingIntent.getActivity(
                context,
                1,
                tap,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            // A mic session is an ongoing (non-swipeable) notification, so without a stop
            // action the only way to end it is to open the app and find the toggle — for a
            // blind user that is a consent problem, not a cosmetic one. The service is
            // already running when this fires, so startService only redelivers ACTION_STOP
            // to the live onStartCommand (which handles it before any promotion logic).
            val stopPending = PendingIntent.getService(
                context,
                2,
                Intent(context, AssistForegroundService::class.java).apply { action = ACTION_STOP },
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                Notification.Builder(context, CHANNEL_ID)
            } else {
                @Suppress("DEPRECATION")
                Notification.Builder(context)
            }
            return builder
                .setContentTitle(context.getString(R.string.assist_notification_title))
                .setContentText(context.getString(R.string.assist_notification_text))
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentIntent(pending)
                .addAction(
                    Notification.Action.Builder(
                        null,
                        context.getString(R.string.assist_notification_stop),
                        stopPending,
                    ).build(),
                )
                .setOngoing(true)
                .build()
        }
    }
}

