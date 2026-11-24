package org.aihealthy.shiyi.integration.embedded

import android.content.Intent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import nodomain.freeyourgadget.gadgetbridge.activities.ControlCenterv2
import nodomain.freeyourgadget.gadgetbridge.impl.GBDevice
import org.aihealthy.shiyi.core.network.HealthApiClient
import org.aihealthy.shiyi.integration.wearable.HealthMetric
import org.aihealthy.shiyi.integration.wearable.HealthObservation
import java.time.Instant
import java.time.temporal.ChronoUnit

@Composable
fun WearablePanel() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var bands by remember { mutableStateOf<List<GBDevice>>(emptyList()) }
    var chosenAddress by remember { mutableStateOf<String?>(null) }
    var status by remember { mutableStateOf("先进入设备管理，配对并初始化荣耀手环。") }
    var busy by remember { mutableStateOf(false) }
    var preview by remember { mutableStateOf<List<HealthObservation>>(emptyList()) }
    var server by remember { mutableStateOf("") }
    var token by remember { mutableStateOf("") }
    var allowed by remember { mutableStateOf(false) }

    fun refreshDevices() {
        bands = EmbeddedBandReader.bands()
        if (bands.none { it.address == chosenAddress }) {
            chosenAddress = bands.singleOrNull()?.address
            preview = emptyList()
        }
    }

    fun execute(block: suspend () -> Unit) {
        busy = true
        scope.launch {
            try {
                block()
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                status = "操作失败，请检查设备状态或服务器授权，必要时重新同步。"
            } finally {
                busy = false
            }
        }
    }

    LaunchedEffect(Unit) { refreshDevices() }

    Card {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("荣耀手环 · 内嵌驱动", style = MaterialTheme.typography.titleMedium)
            Text("本应用内置 Gadgetbridge 设备管理和 BLE 驱动，不需要另外安装 Gadgetbridge。")
            Button(enabled = !busy, onClick = {
                preview = emptyList()
                context.startActivity(Intent(context, ControlCenterv2::class.java))
            }) { Text("设备管理 / 蓝牙配对") }
            OutlinedButton(enabled = !busy, onClick = {
                refreshDevices()
                status = if (bands.isEmpty()) "尚未配对荣耀手环 4。" else "已刷新设备列表。"
            }) { Text("刷新设备") }
            for (band in bands) {
                Row {
                    RadioButton(selected = chosenAddress == band.address, enabled = !busy,
                        onClick = { chosenAddress = band.address; preview = emptyList() })
                    Text(band.name + if (band.isInitialized) " · 已就绪" else " · 未就绪")
                }
            }
            val selected = bands.firstOrNull { it.address == chosenAddress }
            Button(enabled = !busy && selected != null, onClick = {
                execute {
                    refreshDevices()
                    val band = bands.first { it.address == chosenAddress }
                    EmbeddedBandReader.sync(band)
                    status = "已请求同步。请在设备管理中确认同步结束，再读取本地记录。"
                }
            }) { Text("同步手环历史数据") }
            Row {
                Checkbox(checked = allowed, enabled = !busy, onCheckedChange = {
                    allowed = it
                    if (!it) preview = emptyList()
                })
                Text("同意在此页面读取所选手环的本地健康记录")
            }
            Button(enabled = !busy && selected != null && allowed, onClick = {
                preview = emptyList()
                execute {
                    val band = EmbeddedBandReader.bands().first { it.address == chosenAddress }
                    val end = Instant.now()
                    preview = EmbeddedBandReader(band).read(end.minus(7, ChronoUnit.DAYS), end)
                    status = if (preview.isEmpty()) "暂无有效记录，先完成设备同步。"
                             else "已读取 " + preview.size + " 条记录。"
                }
            }) { Text("读取最近七天") }
            for (metric in listOf(HealthMetric.HEART_RATE, HealthMetric.STEPS, HealthMetric.SLEEP)) {
                val records = preview.filter { it.metric == metric }
                Text(metric.label + "：" + (records.lastOrNull()?.value?.toString() ?: "暂无数据") +
                    " · " + records.size + " 条")
            }
            Text("步数为单个区间，睡眠为记录时段，不代表精确睡眠阶段。")
            HorizontalDivider()
            Text("可选：上传到团队 HTTPS 后端")
            OutlinedTextField(value = server, onValueChange = { server = it }, enabled = !busy,
                label = { Text("HTTPS 服务地址") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(value = token, onValueChange = { token = it }, enabled = !busy,
                label = { Text("注册账号 access token") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                modifier = Modifier.fillMaxWidth())
            val validServer = !busy && server.isNotBlank() && token.isNotBlank()
            Button(enabled = validServer && allowed && preview.isNotEmpty(), onClick = {
                execute {
                    HealthApiClient(server, token).consent(preview.map { it.metric }.toSet(),
                        true, EmbeddedBandReader.SOURCE)
                    status = "已授权服务器采集所选指标。"
                }
            }) { Text("授权服务器采集") }
            Button(enabled = validServer && allowed && preview.isNotEmpty(), onClick = {
                execute {
                    val count = HealthApiClient(server, token).upload(preview)
                    status = "服务器已接收 " + count + " 条记录（含幂等重传）。"
                }
            }) { Text("上传预览记录") }
            OutlinedButton(enabled = validServer, onClick = {
                execute {
                    HealthApiClient(server, token).consent(HealthMetric.entries.toSet(), false,
                        EmbeddedBandReader.SOURCE)
                    status = "已撤回服务器采集授权。"
                }
            }) { Text("撤回服务器授权") }
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            Text(status, style = MaterialTheme.typography.bodySmall)
        }
    }
}
