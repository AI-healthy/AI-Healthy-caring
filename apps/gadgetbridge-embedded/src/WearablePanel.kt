package org.aihealthy.shiyi.integration.embedded

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.localbroadcastmanager.content.LocalBroadcastManager
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
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.withTimeoutOrNull
import nodomain.freeyourgadget.gadgetbridge.devices.DeviceManager
import nodomain.freeyourgadget.gadgetbridge.devices.DeviceCoordinator
import nodomain.freeyourgadget.gadgetbridge.model.DeviceType
import nodomain.freeyourgadget.gadgetbridge.impl.GBDevice
import org.aihealthy.shiyi.core.network.HealthApiClient
import org.aihealthy.shiyi.integration.wearable.HealthMetric
import org.aihealthy.shiyi.integration.wearable.HealthObservation
import java.time.Instant
import java.time.temporal.ChronoUnit

@SuppressLint("MissingPermission")
@Composable
fun WearablePanel() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val dashboard = LocalHealthDashboard.current
    val connection = remember(context) { NativeBandConnection(context) }
    val states = remember { mutableStateMapOf<String, NativeBandConnection.State>() }
    val found = remember { mutableStateMapOf<String, NativeBandConnection.Found>() }
    var bands by remember { mutableStateOf<List<GBDevice>>(emptyList()) }
    var scanJob by remember { mutableStateOf<Job?>(null) }
    var scanning by remember { mutableStateOf(false) }
    val seen = remember { mutableStateMapOf<String, Boolean>() }
    var scanError by remember { mutableStateOf("") }
    var manualAddress by remember { mutableStateOf("") }
    var showManual by remember { mutableStateOf(false) }
    var manualModel by remember { mutableStateOf<DeviceType?>(null) }
    var modelMenu by remember { mutableStateOf(false) }
    var modelQuery by remember { mutableStateOf("") }
    var pairingTarget by remember { mutableStateOf<GBDevice?>(null) }
    var pairingKey by remember { mutableStateOf("") }
    var pendingAddress by remember { mutableStateOf<String?>(null) }
    var chosenAddress by remember { mutableStateOf<String?>(null) }
    var status by remember { mutableStateOf("开启蓝牙，搜索并选择附近的智能穿戴设备。") }
    var busy by remember { mutableStateOf(false) }
    var preview by remember { mutableStateOf<List<HealthObservation>>(emptyList()) }
    var server by remember { mutableStateOf("") }
    var token by remember { mutableStateOf("") }
    var allowed by remember { mutableStateOf(false) }

    fun refreshDevices() {
        if (!connection.hasPermissions()) return
        bands = connection.known()
        bands.forEach { states[it.address] = connection.state(it) }
        if (chosenAddress == null) chosenAddress = bands.singleOrNull()?.address
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

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { _ ->
        refreshDevices()
        status = if (connection.hasPermissions()) "蓝牙权限已授权，可以搜索设备。"
                 else "需要附近设备权限；旧版 Android 需要定位权限才能扫描。"
    }
    val locationLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { _ ->
        status = if (connection.hasLocationPermission()) "扫描兼容权限已授权，请再次搜索。"
                 else "未授权定位兼容权限，可尝试直接输入手环蓝牙地址。"
    }
    val enableLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { status = "请确认蓝牙已开启，再搜索设备。" }

    DisposableEffect(context) {
        val manager = LocalBroadcastManager.getInstance(context)
        val receiver = object : BroadcastReceiver() {
            @Suppress("DEPRECATION")
            override fun onReceive(context: Context, intent: Intent) {
                if (intent.action == GBDevice.ACTION_DEVICE_CHANGED) {
                    val device = intent.getParcelableExtra<GBDevice>(GBDevice.EXTRA_DEVICE)
                    if (device != null && device.type.isSupported) {
                        states[device.address] = connection.state(device)
                    }
                }
                if (intent.action == DeviceManager.ACTION_DEVICES_CHANGED) refreshDevices()
            }
        }
        manager.registerReceiver(receiver, IntentFilter().apply {
            addAction(GBDevice.ACTION_DEVICE_CHANGED)
            addAction(DeviceManager.ACTION_DEVICES_CHANGED)
        })
        onDispose {
            manager.unregisterReceiver(receiver)
            scanJob?.cancel()
        }
    }

    LaunchedEffect(Unit) { refreshDevices() }

    fun startSearch() {
        if (!connection.hasPermissions()) {
            permissionLauncher.launch(connection.permissions())
            return
        }
        if (connection.adapter == null) {
            status = "本机没有蓝牙适配器。"
            return
        }
        if (connection.adapter?.isEnabled != true) {
            enableLauncher.launch(Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE))
            return
        }
        if (android.os.Build.VERSION.SDK_INT < 31 && !connection.locationEnabled()) {
            status = "旧版 Android 需要打开系统定位开关才能扫描蓝牙设备。"
            return
        }
        found.clear()
        seen.clear()
        scanError = ""
        refreshDevices()
        runCatching { connection.bonded() }.getOrDefault(emptyList()).forEach {
            found[it.address] = it
        }
        scanning = true
        status = "正在搜索附近的智能穿戴设备…"
        scanJob = scope.launch {
            try {
                withTimeoutOrNull(30000L) {
                    connection.scan().collect { event ->
                        seen[event.address] = true
                        event.match?.let { found[it.address] = it }
                    }
                }
                status = if (found.isEmpty() && bands.isEmpty())
                    if (seen.isEmpty()) "未收到任何 BLE 广播，请检查系统权限、定位开关与蓝牙状态。"
                    else "收到附近设备广播，但未匹配到受支持的设备。请断开其他连接或手动输入地址。"
                    else "请选择要连接的手环。"
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                scanError = e.message.orEmpty()
                status = "扫描失败，请检查蓝牙和系统权限。"
            } finally {
                scanning = false
            }
        }
    }

    fun connectBand(device: GBDevice, systemBond: Boolean = false, authKey: String = "") {
        scanJob?.cancel()
        chosenAddress = device.address
        preview = emptyList()
        execute {
            pendingAddress = device.address
            status = "正在连接并认证；如果手环显示确认请求，请在手环上确认。"
            try {
                connection.connect(device, systemBond, authKey)
                val ready = withTimeoutOrNull(90000L) {
                    while (states[device.address]?.ready != true) {
                        delay(400)
                    }
                    true
                } == true
                refreshDevices()
                status = if (ready) "手环已连接并完成认证，可以同步健康记录。"
                         else "连接尚未就绪，请检查手环确认、其他蓝牙连接和设备状态后重试。"
            } finally {
                pendingAddress = null
            }
        }
    }

    pairingTarget?.let { target ->
        val kind = connection.pairingKind(target)
        AlertDialog(
            onDismissRequest = { pairingTarget = null; pairingKey = "" },
            title = { Text("连接 " + target.name) },
            text = {
                Column {
                    Text(if (kind == DeviceCoordinator.BONDING_STYLE_REQUIRE_KEY)
                        "该型号需要你从合法设备账户取得的认证密钥。密钥仅保存在本机驱动配置。"
                        else "该型号支持系统配对，也可以尝试直接连接。")
                    if (kind == DeviceCoordinator.BONDING_STYLE_REQUIRE_KEY) {
                        OutlinedTextField(value = pairingKey, onValueChange = { pairingKey = it },
                            label = { Text("设备认证密钥") }, singleLine = true,
                            visualTransformation = PasswordVisualTransformation())
                    }
                }
            },
            confirmButton = {
                TextButton(enabled = kind != DeviceCoordinator.BONDING_STYLE_REQUIRE_KEY || pairingKey.isNotBlank(),
                    onClick = {
                        val key = pairingKey
                        pairingKey = ""; pairingTarget = null
                        connectBand(target, true, key)
                    }) { Text("系统配对并连接") }
            },
            dismissButton = {
                TextButton(onClick = {
                    pairingTarget = null; pairingKey = ""
                    if (kind == DeviceCoordinator.BONDING_STYLE_ASK) connectBand(target, false)
                }) { Text(if (kind == DeviceCoordinator.BONDING_STYLE_ASK) "直接连接" else "取消") }
            }
        )
    }

    Card {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("智能穿戴", style = MaterialTheme.typography.titleMedium)
            Text("搜索支持的手环、手表等设备；健康指标按设备适配能力提供。")
            if (scanning) {
                LinearProgressIndicator(Modifier.fillMaxWidth())
                OutlinedButton(onClick = {
                    scanJob?.cancel()
                    status = "已停止搜索，请选择设备。"
                }) { Text("停止搜索") }
            } else {
                Button(enabled = !busy, onClick = { startSearch() }) {
                    Text("搜索附近手环")
                }
            }
            Text("本次扫描：附近设备 " + seen.size + " 个，匹配手环 " + found.size + " 个",
                style = MaterialTheme.typography.bodySmall)
            if (scanError.isNotBlank()) Text("扫描错误：" + scanError)
            if (!scanning && !busy && android.os.Build.VERSION.SDK_INT >= 31 &&
                !connection.hasLocationPermission()) {
                OutlinedButton(onClick = { locationLauncher.launch(connection.locationPermissions()) }) {
                    Text("启用扫描兼容权限（仅用于设备发现）")
                }
            }
            if (!scanning && !busy) {
                OutlinedButton(onClick = { showManual = !showManual }) {
                    Text(if (showManual) "收起手动连接" else "找不到设备？手动输入蓝牙地址")
                }
                if (showManual) {
                    Text("输入自己的设备蓝牙地址；无法自动识别时，请选择实际型号。")
                    OutlinedTextField(value = manualAddress, onValueChange = { manualAddress = it },
                        label = { Text("蓝牙 MAC 地址") }, singleLine = true,
                        modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(value = modelQuery, onValueChange = {
                        modelQuery = it; modelMenu = true
                    }, label = { Text("搜索型号（可选）") }, singleLine = true,
                        modifier = Modifier.fillMaxWidth())
                    Box {
                        OutlinedButton(onClick = { modelMenu = true }) {
                            Text(manualModel?.let { connection.modelLabel(it) } ?: "自动识别 / 选择型号")
                        }
                        DropdownMenu(expanded = modelMenu, onDismissRequest = { modelMenu = false }) {
                            DropdownMenuItem(text = { Text("自动识别") }, onClick = {
                                manualModel = null; modelMenu = false
                            })
                            connection.models().filter {
                                connection.modelLabel(it).contains(modelQuery, true) || it.name.contains(modelQuery, true)
                            }.forEach { model ->
                                DropdownMenuItem(text = { Text(connection.modelLabel(model)) }, onClick = {
                                    manualModel = model; modelMenu = false
                                })
                            }
                        }
                    }
                    Button(enabled = manualAddress.isNotBlank(), onClick = {
                        if (!connection.hasPermissions()) permissionLauncher.launch(connection.permissions())
                        else {
                            try {
                                val band = connection.manual(manualAddress, manualModel)
                                found[band.address] = band
                                status = "已添加待连接设备，请点击连接手环。"
                            } catch (_: Exception) {
                                status = "无法添加，请检查地址格式、设备类型和蓝牙状态。"
                            }
                        }
                    }) { Text("添加手环") }
                }
            }
            val addresses = (bands.map { it.address } + found.keys + listOfNotNull(pendingAddress)).distinct()
            if (addresses.isEmpty()) Text("尚未发现设备。")
            for (address in addresses) {
                val candidate = found[address]
                val known = bands.firstOrNull { it.address == address }
                val device = known ?: candidate?.device
                val state = states[address]
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                    Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(state?.name ?: candidate?.name ?: known?.name ?: "智能穿戴设备",
                            style = MaterialTheme.typography.titleSmall)
                        Text(when {
                            state?.ready == true -> if (state.busy) "同步中" else "已连接"
                            state?.connecting == true || pendingAddress == address -> "连接认证中"
                            known != null -> "已配对 · 未连接"
                            else -> "附近设备"
                        } + (candidate?.takeIf { it.rssi != -1 }?.let { " · 信号 " + it.rssi + " dBm" } ?: ""))
                        if (device != null) {
                            Text(connection.modelLabel(device.type), style = MaterialTheme.typography.bodySmall)
                            if (!connection.supportsNativePairing(device)) {
                                Text("已识别：该型号需要专用配对适配，或仅支持扫描。")
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                if (state?.ready == true) {
                                    OutlinedButton(enabled = !busy, onClick = {
                                        execute {
                                            connection.disconnect(device)
                                            status = "已请求断开连接。"
                                        }
                                    }) { Text("断开") }
                                    OutlinedButton(enabled = !busy, onClick = {
                                        chosenAddress = address; preview = emptyList()
                                    }) { Text(if (chosenAddress == address) "已选择" else "选择") }
                                } else {
                                    Button(enabled = !busy && state?.connecting != true &&
                                        connection.supportsNativePairing(device),
                                        onClick = {
                                            val kind = connection.pairingKind(device)
                                            if (known == null && (kind == DeviceCoordinator.BONDING_STYLE_ASK ||
                                                    kind == DeviceCoordinator.BONDING_STYLE_REQUIRE_KEY)) {
                                                pairingTarget = device; pairingKey = ""
                                            } else connectBand(device)
                                        }) { Text("连接设备") }
                                }
                            }
                        }
                    }
                }
            }
            val selected = bands.firstOrNull { it.address == chosenAddress }
            val selectedState = chosenAddress?.let { states[it] }
            Button(enabled = !busy && !scanning && selected != null &&
                selectedState?.ready == true && !selectedState.busy &&
                selected.deviceCoordinator.supportsActivityDataFetching() && dashboard?.syncing != true, onClick = {
                execute {
                    val band = connection.known().first { it.address == chosenAddress }
                    status = if (dashboard != null && EmbeddedBandReader.supports(band)) dashboard.requestSync(band)
                    else {
                        EmbeddedBandReader.sync(band)
                        "已请求同步；同步完成后点击读取最近七天。"
                    }
                }
            }) { Text("同步手环历史数据") }
            DashboardSettings(selected)
            val hasReader = selected?.let { EmbeddedBandReader.supports(it) } == true
            if (selected != null && !hasReader) Text("此设备可连接；时宜健康数据转换适配尚未开放。")
            Row {
                Checkbox(checked = allowed, enabled = !busy, onCheckedChange = {
                    allowed = it
                    if (!it) preview = emptyList()
                })
                Text("同意在此页面读取所选手环的本地健康记录")
            }
            Button(enabled = !busy && !scanning && selected != null && hasReader && allowed && selectedState?.busy != true, onClick = {
                preview = emptyList()
                execute {
                    val band = connection.known().first { it.address == chosenAddress }
                    val end = Instant.now()
                    preview = EmbeddedBandReader(band).read(end.minus(7, ChronoUnit.DAYS), end)
                    dashboard?.useLocalRead(band, preview, end)
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
