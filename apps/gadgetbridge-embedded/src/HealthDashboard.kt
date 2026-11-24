package org.aihealthy.shiyi.integration.embedded

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.localbroadcastmanager.content.LocalBroadcastManager
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.withTimeoutOrNull
import nodomain.freeyourgadget.gadgetbridge.GBApplication
import nodomain.freeyourgadget.gadgetbridge.impl.GBDevice
import org.aihealthy.shiyi.integration.wearable.HealthObservation
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit

val LocalHealthDashboard = staticCompositionLocalOf<HealthDashboardState?> { null }

/** One foreground controller shared by Today and My tabs. Never uploads automatically. */
class HealthDashboardState(private val context: Context) {
    private val prefs = context.getSharedPreferences("shiyi_health_dashboard", Context.MODE_PRIVATE)
    private val syncGate = Mutex()
    private var awaiting: Pair<String, CompletableDeferred<Unit>>? = null
    var primaryAddress by mutableStateOf(prefs.getString("primary_device", null))
        private set
    var summary by mutableStateOf<DailyHealthSummary?>(null)
        private set
    var deviceName by mutableStateOf<String?>(null)
        private set
    var connected by mutableStateOf(false)
        private set
    var syncing by mutableStateOf(false)
        private set
    var lastRead by mutableStateOf<Instant?>(null)
        private set
    var status by mutableStateOf("在「我的」选择主设备并开启自动同步。")
        private set

    fun enable(device: GBDevice) {
        require(EmbeddedBandReader.supports(device))
        if (primaryAddress != device.address) {
            summary = null; lastRead = null
        }
        primaryAddress = device.address
        prefs.edit().putString("primary_device", device.address).apply()
        deviceName = device.name
        connected = device.isInitialized
        status = "已授权本地读取，前台自动同步已开启。"
    }

    fun disable() {
        primaryAddress = null
        prefs.edit().remove("primary_device").apply()
        summary = null; deviceName = null; connected = false; lastRead = null
        status = "已停止自动同步及首页数据展示。"
    }

    private fun selected(): GBDevice? {
        val address = primaryAddress ?: return null
        return EmbeddedBandReader.bands().firstOrNull { it.address == address }
    }

    fun onData(device: GBDevice?) {
        if (device == null) return
        val pending = awaiting
        if (pending != null && pending.first == device.address) pending.second.complete(Unit)
    }

    fun useLocalRead(device: GBDevice, records: List<HealthObservation>, now: Instant) {
        if (primaryAddress != device.address) return
        summary = DailyHealthAggregator.summarize(records, now, ZoneId.systemDefault())
        deviceName = device.name
        lastRead = now
    }

    suspend fun refreshLocal() {
        val address = primaryAddress ?: return
        val device = selected()
        if (device == null) {
            connected = false
            summary = null
            lastRead = null
            status = "主设备不在设备列表中，请重新选择。"
            return
        }
        deviceName = device.name
        connected = device.isInitialized
        val now = Instant.now()
        try {
            val records = EmbeddedBandReader(device).read(now.minus(7, ChronoUnit.DAYS), now)
            if (primaryAddress == address) useLocalRead(device, records, now)
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            if (primaryAddress == address) status = "读取本地健康记录失败，可稍后重试。"
        }
    }

    fun due(device: GBDevice): Boolean {
        val previous = prefs.getLong("last_attempt_" + device.address, 0L)
        val elapsed = System.currentTimeMillis() - previous
        return previous == 0L || elapsed < 0L || elapsed >= 15 * 60 * 1000L
    }

    suspend fun tick() {
        refreshLocal()
        val device = selected() ?: return
        if (device.isInitialized && !device.isBusy && due(device)) requestSync(device)
    }

    /** Register completion before sending the command. The event is completion, not proof of fresh data. */
    suspend fun requestSync(device: GBDevice): String {
        if (!syncGate.tryLock()) return "已有同步请求正在执行。"
        try {
            if (!device.isInitialized || device.isBusy) return "设备尚未就绪或正在忙，请稍后重试。"
            prefs.edit().putLong("last_attempt_" + device.address, System.currentTimeMillis()).apply()
            val completion = CompletableDeferred<Unit>()
            awaiting = device.address to completion
            syncing = true
            if (primaryAddress == device.address) status = "正在同步手环历史记录…"
            EmbeddedBandReader.sync(device)
            val finished = withTimeoutOrNull(120000L) { completion.await(); true } == true
            if (primaryAddress == device.address) {
                refreshLocal()
                status = if (finished) "驱动同步结束，已刷新本地记录。"
                         else "未收到同步结束通知；显示已有本地记录。"
            }
            return if (finished) "驱动同步结束，可读取本地记录。"
                   else "同步超时，未确认结束；请检查设备状态后重试。"
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            if (primaryAddress == device.address) status = "同步请求失败，保留已有本地记录。"
            return "同步请求失败，请检查设备状态。"
        } finally {
            awaiting = null
            syncing = false
            syncGate.unlock()
        }
    }
}

@Composable
fun HealthDashboardHost(activity: ComponentActivity, content: @Composable () -> Unit) {
    val context = activity.applicationContext
    val dashboard = remember(context) { HealthDashboardState(context) }
    var foreground by remember { mutableStateOf(activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) }
    DisposableEffect(activity, dashboard) {
        val observer = LifecycleEventObserver { _, _ ->
            foreground = activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)
        }
        activity.lifecycle.addObserver(observer)
        val manager = LocalBroadcastManager.getInstance(context)
        val receiver = object : BroadcastReceiver() {
            @Suppress("DEPRECATION")
            override fun onReceive(context: Context, intent: Intent) {
                dashboard.onData(intent.getParcelableExtra<GBDevice>(GBDevice.EXTRA_DEVICE))
            }
        }
        manager.registerReceiver(receiver, IntentFilter(GBApplication.ACTION_NEW_DATA))
        onDispose {
            manager.unregisterReceiver(receiver)
            activity.lifecycle.removeObserver(observer)
        }
    }
    // Only run while the activity is resumed; no new background jobs or permissions.
    LaunchedEffect(foreground, dashboard.primaryAddress) {
        if (foreground && dashboard.primaryAddress != null) {
            while (true) {
                dashboard.tick()
                delay(60000L)
            }
        }
    }
    CompositionLocalProvider(LocalHealthDashboard provides dashboard, content = content)
}

@Composable
fun DashboardSettings(device: GBDevice?) {
    val dashboard = LocalHealthDashboard.current ?: return
    val enabled = dashboard.primaryAddress != null
    val isPrimary = device != null && dashboard.primaryAddress == device.address
    HorizontalDivider()
    Text("首页健康数据", style = MaterialTheme.typography.titleSmall)
    Text("授权后读取所选主设备的本地记录，并在 App 前台每约 15 分钟自动请求同步。不会自动上传。",
        style = MaterialTheme.typography.bodySmall)
    if (device != null && EmbeddedBandReader.supports(device) && !isPrimary) {
        Button(onClick = { dashboard.enable(device) }) { Text("授权并设为首页主设备") }
    }
    if (enabled) {
        Text("已开启：" + (dashboard.deviceName ?: "主设备"))
        OutlinedButton(onClick = { dashboard.disable() }) { Text("关闭自动同步与首页展示") }
    } else if (device == null || !EmbeddedBandReader.supports(device)) {
        Text("请先选择支持健康数据读取的手环。")
    }
}

@Composable
fun HealthOverviewCard(onManage: () -> Unit) {
    val dashboard = LocalHealthDashboard.current ?: return
    val summary = dashboard.summary
    val formatter = DateTimeFormatter.ofPattern("MM-dd HH:mm").withZone(ZoneId.systemDefault())
    Card(colors = CardDefaults.cardColors(containerColor = Color(0xFFFBE8EE))) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("今日健康", style = MaterialTheme.typography.titleLarge)
            if (dashboard.primaryAddress == null) {
                Text("连接手环后，授权在首页展示真实健康记录。")
            } else {
                Text((dashboard.deviceName ?: "主设备") + if (dashboard.connected) " · 已连接" else " · 未连接")
                if (dashboard.syncing) LinearProgressIndicator(Modifier.fillMaxWidth())
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    MetricTile("最近心率", summary?.heartRate?.let { it.toString() + " bpm" } ?: "暂无数据",
                        summary?.heartRateAt?.let { formatter.format(it) } ?: "测量时间未知", Modifier.weight(1f))
                    MetricTile("今日步数", summary?.steps?.let { it.toString() + " 步" } ?: "暂无数据",
                        summary?.date?.toString() ?: "按手机日期", Modifier.weight(1f))
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    MetricTile("昨夜睡眠记录", summary?.sleepMinutes?.let { (it / 60).toString() + " 小时 " + (it % 60) + " 分" } ?: "暂无数据",
                        "昨 18:00 至今 12:00", Modifier.weight(1f))
                    MetricTile("压力状态", "待评估", "尚未启用估计算法", Modifier.weight(1f))
                }
                Text(dashboard.lastRead?.let { "本地读取：" + formatter.format(it) } ?: "尚未读取本地记录",
                    style = MaterialTheme.typography.bodySmall)
            }
            Text(dashboard.status, style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = onManage) { Text("管理穿戴设备") }
        }
    }
}

@Composable
private fun MetricTile(label: String, value: String, note: String, modifier: Modifier = Modifier) {
    Card(modifier = modifier, colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(label, style = MaterialTheme.typography.labelMedium)
            Text(value, style = MaterialTheme.typography.titleMedium)
            Text(note, style = MaterialTheme.typography.bodySmall)
        }
    }
}
