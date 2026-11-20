package com.adaptiveai.mobile.assist

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.ClipData
import android.content.ClipboardManager
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class AdaptiveAccessibilityService : AccessibilityService() {

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        when (event.eventType) {
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> {
                val pkg = event.packageName?.toString() ?: return
                if (pkg != packageName) foregroundPackage = pkg
            }
        }
    }

    override fun onInterrupt() {}

    override fun onUnbind(intent: android.content.Intent?): Boolean {
        if (instance === this) instance = null
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        super.onDestroy()
    }

    companion object {
        @Volatile
        var instance: AdaptiveAccessibilityService? = null
            private set

        @Volatile
        var foregroundPackage: String? = null
            private set

        private const val DEFAULT_NODE_LIMIT = 500
        private const val GESTURE_TIMEOUT_MS = 3000L

        // Nodes from the most recent captureTree(), addressable by the ids handed to JS.
        private val nodeCache = HashMap<Int, AccessibilityNodeInfo>()
        private val nextNodeId = AtomicInteger(0)

        // Ids handed out by findByText(). Unlike captureTree(), a search does not bump the
        // generation or clear the cache, so its entries are tracked separately and recycled
        // by the next search — repeated findByText() calls without a read would otherwise
        // grow nodeCache without bound.
        private val findMatchIds = ArrayList<Int>()

        // Ids are namespaced by read generation. Without this, id 2 from an older read would
        // silently resolve to whatever element happens to be second now — the agent could tap or
        // type into the wrong control, which is unacceptable when acting for a blind user.
        @Volatile
        private var generation = 0

        private fun stale(id: Int): Boolean = id / 10_000 != generation

        // captureTree()/findByText() mutate and recycle cache entries on the bridge thread
        // while clickNode()/scrollNode()/fillNode() run on their own worker threads and act
        // on the very same objects. On API < 33 (Android 7–12, i.e. the Android 11 target)
        // recycle() releases the native info, so an in-flight performAction could run against
        // a freed node — a silent no-op or a wrong-element tap, which is unacceptable when
        // acting for a blind user. Every reader therefore takes an independent obtain() copy
        // under the lock and recycles only its own copy; the cached originals are recycled
        // only under this same lock.
        private val cacheLock = Any()

        private fun requireNode(id: Int): AccessibilityNodeInfo = synchronized(cacheLock) {
            if (stale(id)) {
                throw IllegalStateException("Node $id is from an older screen read; call read_screen again")
            }
            val cached = nodeCache[id]
                ?: throw IllegalStateException("Node $id is not on the current screen; call read_screen again")
            AccessibilityNodeInfo.obtain(cached)
        }

        private fun recycleOwned(node: AccessibilityNodeInfo?) {
            if (node != null && Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                runCatching { node.recycle() }
            }
        }

        fun isRunning(): Boolean = instance != null

        fun captureTree(limit: Int = DEFAULT_NODE_LIMIT): JSONObject {
            // Ids are namespaced by generation (generation * 10_000 + n). A limit >= 10_000
            // would collide with the next generation's bucket and make a stale id resolve to
            // a different element — clamp hard at 9_999.
            val safeLimit = limit.coerceIn(1, 9999)
            val svc = instance ?: throw IllegalStateException("Accessibility service is not enabled")
            val root = svc.rootInActiveWindow
                ?: throw IllegalStateException("No active window (is the screen on and unlocked?)")

            synchronized(cacheLock) {
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                    nodeCache.values.forEach { runCatching { it.recycle() } }
                }
                nodeCache.clear()
                findMatchIds.clear()
                generation += 1
                nextNodeId.set(generation * 10_000)
            }

            val nodes = JSONArray()
            val count = AtomicInteger(0)
            try {
                walk(root, 0, nodes, count, safeLimit)

                val result = JSONObject().apply {
                    put("package", foregroundPackage ?: root.packageName?.toString().orEmpty())
                    put("nodeCount", count.get())
                    put("truncated", count.get() >= safeLimit)
                    put("nodes", nodes)
                }
                return result
            } finally {
                // On API < 33 the receiver of rootInActiveWindow must recycle() it; the node
                // cache holds independent obtain() copies, so the tree stays addressable.
                // finally, not a trailing call: walk() does per-child binder round-trips and
                // can throw when the window is torn down mid-read, which used to leak a node
                // per failed read on API 30.
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                    runCatching { root.recycle() }
                }
            }
        }

        private fun walk(
            node: AccessibilityNodeInfo?,
            depth: Int,
            out: JSONArray,
            count: AtomicInteger,
            limit: Int,
        ) {
            if (node == null || count.get() >= limit) return
            if (depth > 40) return

            val bounds = Rect()
            node.getBoundsInScreen(bounds)
            val visible = node.isVisibleToUser && bounds.width() > 0 && bounds.height() > 0

            // Leaf-only pruning keeps the payload small enough for a single NIM prompt.
            val isInteractive = node.isClickable || node.isLongClickable || node.isEditable ||
                node.isScrollable || node.isCheckable
            val hasText = !node.text.isNullOrBlank() || !node.contentDescription.isNullOrBlank()

            if (visible && (isInteractive || hasText)) {
                val id = nextNodeId.incrementAndGet()
                synchronized(cacheLock) { nodeCache[id] = AccessibilityNodeInfo.obtain(node) }
                count.incrementAndGet()
                out.put(serialize(id, node, bounds, depth))
            }

            for (i in 0 until node.childCount) {
                if (count.get() >= limit) break
                val child = node.getChild(i)
                walk(child, depth + 1, out, count, limit)
                // getChild() hands back a fresh native instance; on API < 33 it must be
                // recycle()d once traversal of that node finishes. Cached nodes are
                // independent obtain() copies, so recycling here never frees live state.
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                    runCatching { child?.recycle() }
                }
            }
        }

        private fun serialize(
            id: Int,
            node: AccessibilityNodeInfo,
            bounds: Rect,
            depth: Int,
        ): JSONObject = JSONObject().apply {
            put("id", id)
            put("d", depth)
            put("cls", node.className?.toString()?.substringAfterLast('.').orEmpty())
            // Password values and labels must never reach the model or logs.
            if (node.isPassword) {
                put("text", "••••••••")
            } else {
                node.text?.takeIf { it.isNotBlank() }?.let { put("text", it.toString()) }
                node.contentDescription?.takeIf { it.isNotBlank() }?.let { put("desc", it.toString()) }
            }
            node.viewIdResourceName?.let { put("res", it) }
            put("b", JSONArray().apply {
                put(bounds.left); put(bounds.top); put(bounds.right); put(bounds.bottom)
            })
            put("cx", bounds.centerX())
            put("cy", bounds.centerY())
            if (node.isClickable) put("click", true)
            if (node.isLongClickable) put("longClick", true)
            if (node.isEditable) put("editable", true)
            if (node.isScrollable) put("scroll", true)
            if (node.isCheckable) put("checkable", true)
            if (node.isChecked) put("checked", true)
            if (node.isSelected) put("selected", true)
            if (node.isFocused) put("focused", true)
            if (!node.isEnabled) put("disabled", true)
            if (node.isPassword) put("password", true)
        }

        fun fillNode(id: Int, value: String): JSONObject {
            val node = requireNode(id)
            try {
                if (!node.isEditable) {
                    // Some fields report non-editable but accept text on their inner TextView.
                    val target = findEditableDescendant(node)
                        ?: throw IllegalStateException("Node $id is not an editable field")
                    try {
                        return performSetText(target, value)
                    } finally {
                        recycleOwned(target)
                    }
                }
                return performSetText(node, value)
            } finally {
                // Our own copy — the cached original may already have been recycled by a
                // concurrent readScreen() on the bridge thread.
                recycleOwned(node)
            }
        }

        private fun findEditableDescendant(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
            for (i in 0 until node.childCount) {
                val child = node.getChild(i) ?: continue
                if (child.isEditable) return child
                val found = findEditableDescendant(child)
                // Recycle every explored child; the returned match is the caller's.
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                    runCatching { child.recycle() }
                }
                if (found != null) return found
            }
            return null
        }

        private fun performSetText(node: AccessibilityNodeInfo, value: String): JSONObject {
            // Fast path: most standard EditTexts accept SET_TEXT as soon as they are focused, so
            // do NOT sleep here — a voice task's speed is the whole point. Only the paste fallback
            // below pays the focus-settle delay, because pastes routinely get dropped in the same
            // frame as focus. Runs on a worker thread (fillNode is threaded in AdaptiveModule).
            node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
            val args = Bundle().apply {
                putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, value)
            }
            val setOk = node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
            if (setOk && textMatches(node, value)) {
                // The field actually holds the text now — verify, don't trust the boolean.
                return JSONObject().apply {
                    put("ok", true)
                    put("method", "set_text")
                    put("text", value)
                }
            }
            // ACTION_SET_TEXT is not supported by every control: many real apps (Flipkart,
            // Amazon, YouTube, web-view search boxes, custom editors) ignore it or apply it
            // asynchronously, so type/search/order would silently do nothing. Fall back to
            // pasting the text into the focused field — the same path a human long-press
            // "Paste" uses, which every editable control honours.
            return pasteText(node, value)
        }

        /**
         * Returns true when the value is now visible anywhere in the active window. We cannot
         * trust the [node] reference we were handed — it is a snapshot taken before the app
         * re-rendered, so its .text never updates. Instead re-query the live tree: if the typed
         * value appears as any node's text, the field took it.
         */
        private fun textMatches(node: AccessibilityNodeInfo, expected: String): Boolean {
            val want = expected.trim()
            if (want.isEmpty()) return false
            val nodeText = node.text?.toString()?.trim()
            if (nodeText == want || nodeText?.contains(want, ignoreCase = true) == true) return true
            val svc = instance ?: return false
            val root = svc.rootInActiveWindow ?: return false
            val found = collectMatchesByTextOrDesc(root, want)
            try {
                // Same matcher as findByText(): any node whose text or contentDescription
                // contains the value (case-insensitive). YouTube's search field and other
                // OEMs apply SET_TEXT asynchronously or via the label, so exact-equality
                // verification used to report fills on those fields as failures.
                return found.isNotEmpty()
            } finally {
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                    runCatching { root.recycle() }
                    found.forEach { runCatching { it.recycle() } }
                }
            }
        }

        private fun sleepQuiet(ms: Long) {
            try { Thread.sleep(ms) } catch (_: InterruptedException) { Thread.currentThread().interrupt() }
        }

        /** Copies [value] to the clipboard and pastes it into [node] (which must be focused). */
        private fun pasteText(node: AccessibilityNodeInfo, value: String): JSONObject {
            val service = instance
                ?: return JSONObject().apply {
                    put("ok", false); put("method", "paste"); put("text", value)
                    put("reason", "service not bound")
                }
            val cm = service.getSystemService(AccessibilityService.CLIPBOARD_SERVICE) as ClipboardManager?
                ?: return JSONObject().apply {
                    put("ok", false); put("method", "paste"); put("text", value)
                    put("reason", "no clipboard")
                }
            try {
                cm.setPrimaryClip(ClipData.newPlainText("adaptiveai", value))
                // Focus, then a short settle so the IME/target app has focused the field, then
                // paste — a paste that lands in the same frame as focus is routinely dropped.
                // Kept to the minimum that reliably works so a fallback fill stays snappy.
                node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
                sleepQuiet(200)
                val pasted = node.performAction(AccessibilityNodeInfo.ACTION_PASTE)
                // Brief window for the (asynchronous) paste to render before verifying.
                sleepQuiet(250)
                if (pasted && textMatches(node, value)) {
                    return JSONObject().apply {
                        put("ok", true); put("method", "paste"); put("text", value)
                    }
                }
                return JSONObject().apply {
                    put("ok", false); put("method", "paste"); put("text", value)
                    put("reason", "target app rejected or did not apply the paste")
                }
            } catch (e: Throwable) {
                return JSONObject().apply {
                    put("ok", false); put("method", "paste"); put("text", value)
                    put("reason", e.message ?: e.javaClass.simpleName)
                }
            }
        }

        /**
         * Walks up at most [maxHops] ancestors looking for the first one matching
         * [predicate]. On API < 33 every intermediate getParent() result is recycle()d; the
         * returned match is the caller's to recycle once it is done with it.
         */
        private fun findMatchingAncestor(
            node: AccessibilityNodeInfo,
            maxHops: Int,
            predicate: (AccessibilityNodeInfo) -> Boolean,
        ): AccessibilityNodeInfo? {
            val canRecycle = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU
            var cur: AccessibilityNodeInfo? = node
            var hops = 0
            while (cur != null && hops < maxHops) {
                val held = cur!!
                val parent = held.parent
                if (canRecycle && held !== node) runCatching { held.recycle() }
                if (parent == null) return null
                if (predicate(parent)) return parent
                cur = parent
                hops++
            }
            // The hop limit cut the walk short: recycle whatever ancestor is still held.
            while (canRecycle && cur != null) {
                val held = cur!!
                cur = held.parent
                runCatching { held.recycle() }
            }
            return null
        }

        fun clickNode(id: Int): Boolean {
            val node = requireNode(id)
            try {
                if (node.isClickable) return node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                // Clickable state often lives on an ancestor wrapper.
                val target = findMatchingAncestor(node, maxHops = 6) { it.isClickable }
                if (target != null) {
                    try {
                        return target.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    } finally {
                        recycleOwned(target)
                    }
                }
                val b = Rect()
                node.getBoundsInScreen(b)
                return tap(b.centerX().toFloat(), b.centerY().toFloat())
            } finally {
                recycleOwned(node)
            }
        }

        fun findByText(query: String): JSONArray {
            val svc = instance ?: throw IllegalStateException("Accessibility service is not enabled")
            val root = svc.rootInActiveWindow ?: return JSONArray()
            // Android's findAccessibilityNodeInfosByText matches only nodes whose text is
            // non-empty. YouTube and many OEMs label their search icon with a
            // contentDescription — "Search" — so a search by label through the framework
            // returned nothing and the agent could never reach the search field. Walk the
            // tree matching text OR contentDescription (case-insensitive substring) instead.
            val matches = collectMatchesByTextOrDesc(root, query)
            // Release the previous search's entries before allocating new ones — under
            // the same lock the action threads take copies in, so a match can never be
            // recycled mid- performAction on another thread.
            synchronized(cacheLock) {
                findMatchIds.forEach { id ->
                    nodeCache.remove(id)?.let {
                        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                            runCatching { it.recycle() }
                        }
                    }
                }
                findMatchIds.clear()
            }
            try {
                val out = JSONArray()
                for (n in matches) {
                    val b = Rect()
                    n.getBoundsInScreen(b)
                    if (!n.isVisibleToUser) continue
                    val id = nextNodeId.incrementAndGet()
                    synchronized(cacheLock) {
                        nodeCache[id] = AccessibilityNodeInfo.obtain(n)
                        findMatchIds.add(id)
                    }
                    out.put(JSONObject().apply {
                        put("id", id)
                        // Same masking as serialize(): never hand password contents to the model.
                        put("text", if (n.isPassword) "••••••••" else n.text?.toString().orEmpty())
                        put("desc", n.contentDescription?.toString().orEmpty())
                        put("cls", n.className?.toString()?.substringAfterLast('.').orEmpty())
                        put("res", n.viewIdResourceName ?: JSONObject.NULL)
                        put("cx", b.centerX())
                        put("cy", b.centerY())
                        put("editable", n.isEditable)
                        put("click", n.isClickable)
                    })
                }
                return out
            } finally {
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                    // Recycle the walk's copies (including ones skipped by the visibility
                    // check) — the cache holds independent obtain() copies that survive.
                    runCatching { root.recycle() }
                    matches.forEach { runCatching { it.recycle() } }
                }
            }
        }

        /**
         * Depth-first walk collecting every node whose text OR contentDescription matches
         * [query] case-insensitively by substring. Returns independent obtain() copies —
         * on API < 33 the walked originals are recycled after the walk.
         */
        private fun collectMatchesByTextOrDesc(
            root: AccessibilityNodeInfo,
            query: String,
        ): List<AccessibilityNodeInfo> {
            val out = mutableListOf<AccessibilityNodeInfo>()
            collectMatchesByTextOrDesc(root, query, out)
            return out
        }

        private fun collectMatchesByTextOrDesc(
            node: AccessibilityNodeInfo,
            query: String,
            out: MutableList<AccessibilityNodeInfo>,
        ) {
            if (nodeMatchesTextOrDesc(node, query)) {
                out.add(AccessibilityNodeInfo.obtain(node))
            }
            for (i in 0 until node.childCount) {
                val child = node.getChild(i) ?: continue
                collectMatchesByTextOrDesc(child, query, out)
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                    runCatching { child.recycle() }
                }
            }
        }

        private fun nodeMatchesTextOrDesc(node: AccessibilityNodeInfo, query: String): Boolean {
            if (query.isEmpty()) return false
            return node.text?.toString()?.contains(query, ignoreCase = true) == true ||
                node.contentDescription?.toString()?.contains(query, ignoreCase = true) == true
        }

        fun scrollNode(id: Int, forward: Boolean): Boolean {
            val node = requireNode(id)
            try {
                val action = if (forward) {
                    AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
                } else {
                    AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
                }
                if (node.isScrollable) return node.performAction(action)
                val target = findMatchingAncestor(node, maxHops = 6) { it.isScrollable }
                    ?: return false
                try {
                    return target.performAction(action)
                } finally {
                    recycleOwned(target)
                }
            } finally {
                recycleOwned(node)
            }
        }

        fun goBack(): Boolean =
            instance?.performGlobalAction(GLOBAL_ACTION_BACK) ?: false

        fun goHome(): Boolean =
            instance?.performGlobalAction(GLOBAL_ACTION_HOME) ?: false

        fun openRecents(): Boolean =
            instance?.performGlobalAction(GLOBAL_ACTION_RECENTS) ?: false

        fun openNotifications(): Boolean =
            instance?.performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS) ?: false

        fun tap(x: Float, y: Float): Boolean =
            stroke(Path().apply { moveTo(x, y) }, 60)

        fun longPress(x: Float, y: Float): Boolean =
            stroke(Path().apply { moveTo(x, y) }, 700)

        fun swipe(x1: Float, y1: Float, x2: Float, y2: Float, durationMs: Long = 320): Boolean {
            val path = Path().apply {
                moveTo(x1, y1)
                lineTo(x2, y2)
            }
            return stroke(path, durationMs)
        }

        private fun stroke(path: Path, durationMs: Long): Boolean {
            val svc = instance ?: throw IllegalStateException("Accessibility service is not enabled")
            val gesture = GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(path, 0, durationMs))
                .build()
            val latch = CountDownLatch(1)
            // null = we never heard back (timeout). false = the system cancelled it.
            // Both used to collapse to `false`, so a slow-but-successful gesture reported
            // failure and the agent retried — firing the tap twice.
            var completed: Boolean? = null
            val cb = object : GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription?) {
                    completed = true
                    latch.countDown()
                }

                override fun onCancelled(gestureDescription: GestureDescription?) {
                    completed = false
                    latch.countDown()
                }
            }
            if (!svc.dispatchGesture(gesture, cb, null)) return false
            val heard = latch.await(GESTURE_TIMEOUT_MS, TimeUnit.MILLISECONDS)
            if (!heard) {
                // Timed out but still in flight: tell JS to re-read the screen instead of
                // retrying blindly (a retry would double-tap).
                return false
            }
            return completed == true
        }
    }
}
