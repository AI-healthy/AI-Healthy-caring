package org.aihealthy.shiyi.integration.healthconnect

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import org.aihealthy.shiyi.core.network.HealthApiClient
import org.aihealthy.shiyi.integration.wearable.HealthMetric
import org.aihealthy.shiyi.integration.wearable.HealthObservation
import java.time.Instant
import java.time.temporal.ChronoUnit

@Composable
fun WearablePanel() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var status by remember { mutableStateOf("先在 Gadgetbridge 中同步手环，再授权读取。") }
    var busy by remember { mutableStateOf(false) }
    var samples by remember { mutableStateOf<List<HealthObservation>>(emptyList()) }
    var server by remember { mutableStateOf("") }
    var token by remember { mutableStateOf("") }
    var packageName by remember { mutableStateOf(HealthConnectAdapter.GADGETBRIDGE_PACKAGE) }
    val available = HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE
    val launcher = rememberLauncherForActivityResult(
        PermissionController.createRequestPermissionResultContract()
    ) { granted ->
        samples = emptyList()
        status = if (granted.containsAll(HealthConnectAdapter.permissions))
            "授权完成，点击读取数据。" else "授权不完整，暂不读取。"
    }

    fun adapter(): HealthConnectAdapter =
        HealthConnectAdapter(HealthConnectClient.getOrCreate(context), packageName.trim())

    fun execute(action: suspend () -> Unit) {
        busy = true
        scope.launch {
            try {
                action()
            } catch (e: CancellationException) {
                throw e
            } catch (_: SecurityException) {
                samples = emptyList()
                status = "权限已撤回或不足，请重新授权。"
            } catch (_: Exception) {
                status = "操作失败：检查 Health Connect、网络、服务端授权或数据冲突。"
            } finally {
                busy = false
            }
        }
    }

    Card {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("智能穿戴 · 健康数据", style = MaterialTheme.typography.titleMedium)
            Text("通过 Gadgetbridge → Health Connect 读取授权记录。当前不是手环直接蓝牙连接。")
            if (!available) {
                Text("Health Connect 当前不可用。请在支持的 Android 手机上安装或更新该服务。")
            }
            OutlinedTextField(
                value = packageName,
                onValueChange = { packageName = it; samples = emptyList() },
                enabled = !busy, singleLine = true,
                label = { Text("数据来源 App 包名") }, modifier = Modifier.fillMaxWidth()
            )
            Button(enabled = available && !busy, onClick = {
                launcher.launch(HealthConnectAdapter.permissions)
            }) { Text("授权读取健康数据") }
            Button(enabled = available && !busy && packageName.isNotBlank(), onClick = {
                samples = emptyList()
                execute {
                    val end = Instant.now()
                    samples = adapter().read(end.minus(7, ChronoUnit.DAYS), end)
                    status = if (samples.isEmpty()) "最近七天没有该来源的记录，请先在 Gadgetbridge 同步。"
                             else "已读取 " + samples.size + " 条真实来源记录。"
                }
            }) { Text("读取最近七天") }
            OutlinedButton(enabled = available && !busy, onClick = {
                samples = emptyList()
                execute {
                    HealthConnectClient.getOrCreate(context).permissionController.revokeAllPermissions()
                    status = "已撤回本 App 的 Health Connect 权限。服务器授权可在下方撤回。"
                }
            }) { Text("撤回本地读取权限") }
            for (metric in HealthMetric.entries) {
                val records = samples.filter { it.metric == metric }
                val latest = records.lastOrNull()
                Text(metric.label + "：" + (latest?.value?.toString() ?: "暂无数据") +
                    if (latest == null) "" else " · 最近一条，" + records.size + " 条记录")
            }
            Text("睡眠值为记录时段的分钟数；步数为单条区间值，不是日累计。")
            HorizontalDivider()
            Text("受控后端联调（可选）", style = MaterialTheme.typography.titleSmall)
            Text("只有明确授权并点击上传才会发送预览中的记录。请仅使用团队可信 HTTPS 服务。")
            OutlinedTextField(
                value = server, onValueChange = { server = it }, singleLine = true, enabled = !busy,
                label = { Text("HTTPS 服务地址") }, modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = token, onValueChange = { token = it }, singleLine = true, enabled = !busy,
                label = { Text("已登录账号的 access token") },
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                modifier = Modifier.fillMaxWidth()
            )
            val canSend = !busy && server.isNotBlank() && token.isNotBlank()
            Button(enabled = canSend && available && samples.isNotEmpty(), onClick = {
                execute {
                    check(adapter().authorized())
                    HealthApiClient(server, token).consent(samples.map { it.metric }.toSet(), true)
                    status = "已为预览中的指标授予服务器采集授权。"
                }
            }) { Text("授权服务器采集预览指标") }
            Button(enabled = canSend && available && samples.isNotEmpty(), onClick = {
                execute {
                    check(adapter().authorized())
                    val count = HealthApiClient(server, token).upload(samples)
                    status = "服务器已接收 " + count + " 条记录（含重复记录）。"
                }
            }) { Text("上传预览记录") }
            OutlinedButton(enabled = canSend, onClick = {
                execute {
                    HealthApiClient(server, token).consent(HealthMetric.entries.toSet(), false)
                    status = "已撤回服务器端四类采集授权。历史记录可通过 API 删除。"
                }
            }) { Text("撤回服务器采集授权") }
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            Text(status, style = MaterialTheme.typography.bodySmall)
        }
    }
}
