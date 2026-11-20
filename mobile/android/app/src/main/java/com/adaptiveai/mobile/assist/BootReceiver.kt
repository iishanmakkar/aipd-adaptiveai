package com.adaptiveai.mobile.assist

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import com.adaptiveai.mobile.MainActivity
import com.adaptiveai.mobile.R

/**
 * On device boot, nudge the user to re-enable background listening.
 *
 * Android 12+ forbids starting a microphone foreground service from the background,
 * so we cannot silently restart the loop after reboot — the user must open the app
 * once (one tap) and the Assistant restart logic re-promotes the service while
 * the app is foreground. The notification below is that one-tap entry point.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED &&
            intent?.action != Intent.ACTION_MY_PACKAGE_REPLACED
        ) return
        showNotification(context)
    }

    private fun showNotification(context: Context) {
        try {
            AssistForegroundService.ensureChannel(context)
            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val tap = Intent(context, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            val pending = PendingIntent.getActivity(
                context, 0, tap,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                Notification.Builder(context, AssistForegroundService.CHANNEL_ID)
            } else {
                @Suppress("DEPRECATION")
                Notification.Builder(context)
            }
            nm.notify(
                4799,
                builder
                    .setContentTitle(context.getString(R.string.assist_notification_title))
                    .setContentText("Tap to start AdaptiveAI voice listening")
                    .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                    .setContentIntent(pending)
                    .build(),
            )
        } catch (e: Exception) {
            // Best-effort: boot nudges must never crash.
        }
    }
}
