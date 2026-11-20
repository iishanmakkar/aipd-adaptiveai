package com.adaptiveai.mobile.assist

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import android.util.Base64
import android.util.DisplayMetrics
import android.view.WindowManager
import androidx.core.content.FileProvider
import com.adaptiveai.mobile.R
import java.io.ByteArrayOutputStream

/**
 * Holds the MediaProjection session.
 *
 * API 34 requires the mediaProjection foreground service to already be running before
 * getMediaProjection() is called, so the projection is created inside CaptureService rather
 * than here — this object only drives the VirtualDisplay once that has happened.
 */
object ScreenCapture {

    const val CHANNEL_ID = "adaptiveai_screen_capture"
    const val NOTIFICATION_ID = 4711
    const val MAX_EDGE = 1024

    @Volatile
    var projection: MediaProjection? = null
        private set

    // release() runs on the main thread (projection onStop, CaptureService teardown) while
    // captureFrame() runs on the RN thread — these must be visible across threads.
    @Volatile
    private var imageReader: ImageReader? = null

    @Volatile
    private var virtualDisplay: VirtualDisplay? = null

    @Volatile
    private var width = 0

    @Volatile
    private var height = 0

    // The most recent share screenshot; the previous one is deleted on the next save so the
    // cache does not accumulate a JPEG per share until the OS decides to purge it.
    @Volatile
    private var lastShareFile: java.io.File? = null

    private val projectionCallback = object : MediaProjection.Callback() {
        override fun onStop() {
            release()
        }
    }

    fun isActive(): Boolean = projection != null

    /** Must be called only from CaptureService, after startForeground() has returned. */
    fun begin(context: Context, resultCode: Int, resultData: Intent): Boolean {
        release()
        val manager = context.getSystemService(Context.MEDIA_PROJECTION_SERVICE)
            as MediaProjectionManager
        val mp = try {
            manager.getMediaProjection(resultCode, resultData)
        } catch (e: Throwable) {
            return false
        } ?: return false

        // Required before createVirtualDisplay on API 34+.
        mp.registerCallback(projectionCallback, null)
        projection = mp

        val metrics = displayMetrics(context)
        // Downscale BEFORE allocating buffers: a full-res 1440×3120 RGBA reader + bitmap
        // is ~36 MB+ and OOMs 3–4 GB devices with an LLM loaded. Capture at MAX_EDGE.
        val rawW = metrics.widthPixels
        val rawH = metrics.heightPixels
        if (rawW <= 0 || rawH <= 0) {
            release()
            return false
        }
        val longest = maxOf(rawW, rawH)
        val scale = if (longest > MAX_EDGE) MAX_EDGE.toFloat() / longest else 1f
        width = (rawW * scale).toInt().coerceAtLeast(1)
        height = (rawH * scale).toInt().coerceAtLeast(1)
        val scaledDpi = (metrics.densityDpi * scale).toInt().coerceAtLeast(72)

        val reader = try {
            ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        } catch (e: OutOfMemoryError) {
            release()
            return false
        }
        imageReader = reader
        virtualDisplay = mp.createVirtualDisplay(
            "AdaptiveAICapture",
            width,
            height,
            scaledDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            reader.surface,
            null,
            null,
        )
        if (virtualDisplay == null) {
            // Without this, isActive() stays true while captureFrame() returns null forever.
            release()
            return false
        }
        return true
    }

    fun release() {
        runCatching { virtualDisplay?.release() }
        runCatching { imageReader?.close() }
        runCatching { projection?.unregisterCallback(projectionCallback) }
        runCatching { projection?.stop() }
        virtualDisplay = null
        imageReader = null
        projection = null
    }

    /** Returns a downscaled JPEG encoded as base64, or null if no frame was available. */
    fun captureFrame(jpegQuality: Int = 72): String? {
        val reader = imageReader ?: return null
        if (projection == null) return null

        // The first frames after VirtualDisplay creation can be empty. Give the display
        // up to one second to produce a frame, which also makes sharing reliable immediately
        // after the consent dialog closes.
        var image: android.media.Image? = null
        var attempts = 0
        while (image == null && attempts < 10 && projection != null) {
            image = runCatching { reader.acquireLatestImage() }.getOrNull()
            if (image == null) {
                try {
                    Thread.sleep(100)
                } catch (e: InterruptedException) {
                    Thread.currentThread().interrupt()
                    break
                }
            }
            attempts++
        }
        val captured = image ?: return null

        val bitmap = try {
            runCatching { imageToBitmap(captured) }.getOrNull()
        } finally {
            runCatching { captured.close() }
        } ?: return null

        val scaled = runCatching { downscale(bitmap) }.getOrNull()
        if (scaled == null) {
            // downscale threw (OOM): the original bitmap would otherwise leak ~2 MB.
            runCatching { bitmap.recycle() }
            return null
        }
        if (scaled !== bitmap) runCatching { bitmap.recycle() }
        val out = ByteArrayOutputStream()
        return try {
            scaled.compress(Bitmap.CompressFormat.JPEG, jpegQuality.coerceIn(20, 95), out)
            scaled.recycle()
            Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
        } catch (e: Throwable) {
            runCatching { scaled.recycle() }
            null
        }
    }

    fun saveFrame(context: Context, jpegQuality: Int = 90): android.net.Uri? {
        val encoded = captureFrame(jpegQuality) ?: return null
        val bytes = runCatching { Base64.decode(encoded, Base64.NO_WRAP) }.getOrNull() ?: return null
        val file = java.io.File(context.cacheDir, "adaptiveai-screen-${System.currentTimeMillis()}.jpg")
        file.writeBytes(bytes)
        lastShareFile?.let { runCatching { if (it != file) it.delete() } }
        lastShareFile = file
        return FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
    }

    private fun imageToBitmap(image: android.media.Image): Bitmap? {
        // Trust the frame's own dimensions, not the cached begin() size — rotation /
        // fold / resize would otherwise stretch or overflow the buffer.
        val imgW = image.width
        val imgH = image.height
        if (imgW <= 0 || imgH <= 0) return null
        val plane = image.planes.firstOrNull() ?: return null
        val buffer = plane.buffer
        val pixelStride = plane.pixelStride
        val rowStride = plane.rowStride
        if (pixelStride == 0) return null
        val rowPadding = rowStride - pixelStride * imgW
        val bmpWidth = imgW + rowPadding / pixelStride
        if (bmpWidth <= 0) return null
        val bmp = Bitmap.createBitmap(bmpWidth, imgH, Bitmap.Config.ARGB_8888)
        bmp.copyPixelsFromBuffer(buffer)
        return if (rowPadding == 0) {
            bmp
        } else {
            Bitmap.createBitmap(bmp, 0, 0, imgW, imgH).also { bmp.recycle() }
        }
    }

    private fun downscale(src: Bitmap): Bitmap {
        val longest = maxOf(src.width, src.height)
        if (longest <= MAX_EDGE) return src
        val factor = MAX_EDGE.toFloat() / longest
        return Bitmap.createScaledBitmap(
            src,
            (src.width * factor).toInt().coerceAtLeast(1),
            (src.height * factor).toInt().coerceAtLeast(1),
            true,
        )
    }

    private fun displayMetrics(context: Context): DisplayMetrics {
        val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val metrics = DisplayMetrics()
        @Suppress("DEPRECATION")
        wm.defaultDisplay.getRealMetrics(metrics)
        return metrics
    }

    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (nm.getNotificationChannel(CHANNEL_ID) != null) return
        nm.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                context.getString(R.string.capture_channel_name),
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = context.getString(R.string.capture_channel_desc)
                setShowBadge(false)
            }
        )
    }

    fun buildNotification(context: Context): Notification {
        // The notification promises "Tap to stop screen capture." — route the tap to the
        // service's ACTION_STOP branch instead of merely opening the app. A PendingIntent
        // fired from a notification tap is exempt from background service-start restrictions,
        // and the service is already foreground while capture is active.
        val stop = Intent(context, CaptureService::class.java).apply { action = CaptureService.ACTION_STOP }
        val pending = PendingIntent.getService(
            context,
            0,
            stop,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(context, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(context)
        }
        return builder
            .setContentTitle(context.getString(R.string.capture_notification_title))
            .setContentText(context.getString(R.string.capture_notification_text))
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentIntent(pending)
            .setOngoing(true)
            .build()
    }
}

class CaptureService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                ScreenCapture.release()
                stopSelf()
                return START_NOT_STICKY
            }
        }

        ScreenCapture.ensureChannel(this)
        val promoted = try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(
                    ScreenCapture.NOTIFICATION_ID,
                    ScreenCapture.buildNotification(this),
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION,
                )
            } else {
                startForeground(ScreenCapture.NOTIFICATION_ID, ScreenCapture.buildNotification(this))
            }
            true
        } catch (e: Throwable) {
            // Typed promotion failed (background start restriction / missing FGS type).
            // startForegroundService() was already called, so the platform now DEMANDS a
            // startForeground() within 5s — calling stopSelf() alone on this path is the
            // documented RemoteServiceException ("did not then call Service.startForeground")
            // that force-closes the app. Retry untyped to satisfy the contract, then stop.
            runCatching {
                startForeground(ScreenCapture.NOTIFICATION_ID, ScreenCapture.buildNotification(this))
            }
            ScreenCapture.release()
            stopSelf()
            return START_NOT_STICKY
        }
        if (!promoted) return START_NOT_STICKY

        val resultCode = intent?.getIntExtra(EXTRA_RESULT_CODE, 0) ?: 0
        val resultData: Intent? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent?.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent?.getParcelableExtra(EXTRA_RESULT_DATA)
        }

        if (resultCode == 0 || resultData == null) {
            stopSelf()
            return START_NOT_STICKY
        }

        val ok = try {
            ScreenCapture.begin(applicationContext, resultCode, resultData)
        } catch (e: Throwable) {
            ScreenCapture.release()
            false
        }
        if (!ok) {
            ScreenCapture.release()
            stopSelf()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        ScreenCapture.release()
        super.onDestroy()
    }

    companion object {
        const val ACTION_STOP = "com.adaptiveai.mobile.assist.CAPTURE_STOP"
        const val EXTRA_RESULT_CODE = "resultCode"
        const val EXTRA_RESULT_DATA = "resultData"

        fun start(context: Context, resultCode: Int, resultData: Intent) {
            val intent = Intent(context, CaptureService::class.java).apply {
                putExtra(EXTRA_RESULT_CODE, resultCode)
                putExtra(EXTRA_RESULT_DATA, resultData)
            }
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(intent)
                } else {
                    context.startService(intent)
                }
            } catch (e: IllegalStateException) {
                // Background start refused (Android 12+): tear down so the JS
                // promise's poll times out instead of hanging a live FGS.
                ScreenCapture.release()
                throw e
            }
        }

        fun stop(context: Context) {
            // stopService is exempt from background-start restrictions; a stop intent
            // delivered via startService would throw from background while live.
            try {
                val intent = Intent(context, CaptureService::class.java)
                context.stopService(intent)
                ScreenCapture.release()
            } catch (e: Throwable) {
                ScreenCapture.release()
            }
        }
    }
}

