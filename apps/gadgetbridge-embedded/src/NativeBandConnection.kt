package org.aihealthy.shiyi.integration.embedded

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.BroadcastReceiver
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.location.LocationManager
import java.util.Locale
import androidx.core.content.ContextCompat
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import nodomain.freeyourgadget.gadgetbridge.GBApplication
import nodomain.freeyourgadget.gadgetbridge.devices.DeviceCoordinator
import nodomain.freeyourgadget.gadgetbridge.util.DeviceHelper
import nodomain.freeyourgadget.gadgetbridge.impl.GBDevice
import nodomain.freeyourgadget.gadgetbridge.impl.GBDeviceCandidate
import nodomain.freeyourgadget.gadgetbridge.model.DeviceType

/** Native discovery and common pairing paths for the pinned Gadgetbridge device registry. */
@SuppressLint("MissingPermission")
class NativeBandConnection(private val context: Context) {
    data class Found(val name: String, val address: String, val rssi: Int, val device: GBDevice)
    data class State(val address: String, val name: String, val ready: Boolean,
                     val connecting: Boolean, val busy: Boolean)

    data class Discovery(val address: String, val match: Found?)

    val adapter: BluetoothAdapter?
        get() = context.getSystemService(BluetoothManager::class.java)?.adapter

    fun permissions(): Array<String> =
        if (Build.VERSION.SDK_INT >= 31) arrayOf(
            Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT
        ) else arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION, Manifest.permission.ACCESS_FINE_LOCATION)

    // The upstream manifest does not use neverForLocation. Some Android builds
    // need foreground location permission for complete scan results.
    fun locationPermissions() = arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION,
        Manifest.permission.ACCESS_FINE_LOCATION)

    fun hasLocationPermission() = ContextCompat.checkSelfPermission(context,
        Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    fun locationEnabled(): Boolean {
        val manager = context.getSystemService(LocationManager::class.java) ?: return false
        return runCatching {
            if (Build.VERSION.SDK_INT >= 28) manager.isLocationEnabled
            else manager.isProviderEnabled(LocationManager.GPS_PROVIDER) ||
                manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
        }.getOrDefault(false)
    }

    fun hasPermissions(): Boolean = permissions().all {
        ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED
    }

    fun known(): List<GBDevice> = GBApplication.app().deviceManager.devices
        .filter { selectable(it.type) }.toList()

    fun state(device: GBDevice): State = State(device.address, device.name, device.isInitialized,
        device.isConnecting || device.isInitializing, device.isBusy)

    // Generic, synthetic and debug coordinators are not real identified wearable models.
    private val excluded = setOf("UNKNOWN", "TEST", "SCANNABLE", "BLE_GATT_CLIENT")
    private fun selectable(type: DeviceType) = type.isSupported && type.name !in excluded

    fun models(): List<DeviceType> = DeviceType.values().filter { selectable(it) }
        .sortedBy { modelLabel(it) }

    fun modelLabel(type: DeviceType): String = runCatching {
        context.getString(type.deviceCoordinator.deviceNameResource)
    }.getOrDefault(type.name)

    private fun identify(bt: BluetoothDevice, advertised: String?, rssi: Int,
                         uuids: Array<android.os.ParcelUuid>?): Found? {
        val candidate = GBDeviceCandidate(bt, rssi.toShort(), uuids)
        candidate.refreshNameIfUnknown()
        // Some peripherals advertise a name before Android caches BluetoothDevice.getName().
        if (!advertised.isNullOrBlank()) candidate.setShiYiAdvertisedName(advertised)
        // Never cache UNKNOWN from an early incomplete scan packet.
        var type = DeviceHelper.getInstance().resolveDeviceType(candidate, false)
        if (!selectable(type) && !advertised.isNullOrBlank()) {
            val cachedName = bt.name
            if (!cachedName.isNullOrBlank() && cachedName != advertised) {
                candidate.setShiYiAdvertisedName(cachedName)
                type = DeviceHelper.getInstance().resolveDeviceType(candidate, false)
            }
        }
        // Preserve the tested Honor 4 name variants if the upstream pattern is stricter.
        if (!selectable(type) && Regex("""^honor[\s_-]*band[\s_-]*4(?:$|[\s_-].*)""",
                RegexOption.IGNORE_CASE).matches(candidate.name.trim())) {
            type = DeviceType.HONORBAND4
        }
        if (!selectable(type)) return null
        val device = type.deviceCoordinator.createDevice(candidate, type)
        return Found(device.name, device.address, rssi, device)
    }

    fun bonded(): List<Found> {
        check(hasPermissions())
        return adapter?.bondedDevices.orEmpty().mapNotNull { bt ->
            runCatching { identify(bt, bt.name, -1, bt.uuids) }.getOrNull()
        }
    }

    /** Manual addition requires explicit model selection when the address cannot be identified. */
    fun manual(address: String, model: DeviceType?): Found {
        check(hasPermissions())
        val normalized = address.trim().uppercase(Locale.ROOT)
        require(BluetoothAdapter.checkBluetoothAddress(normalized)) { "Invalid Bluetooth address" }
        val bt = adapter?.takeIf { it.isEnabled }?.getRemoteDevice(normalized)
            ?: error("Bluetooth unavailable")
        val detected = identify(bt, bt.name, -1, bt.uuids)
        if (detected != null) {
            require(model == null || detected.device.type == model) { "Model mismatch" }
            return detected
        }
        require(model != null && selectable(model)) { "Select the actual device model" }
        val candidate = GBDeviceCandidate(bt, (-1).toShort(), bt.uuids)
        candidate.refreshNameIfUnknown()
        val device = model.deviceCoordinator.createDevice(candidate, model)
        if (!candidate.isNameKnown) device.setName(modelLabel(model))
        return Found(device.name, device.address, -1, device)
    }

    fun scan(): Flow<Discovery> = callbackFlow {
        check(hasPermissions()) { "Missing Bluetooth permission" }
        val bluetooth = adapter?.takeIf { it.isEnabled } ?: error("Bluetooth unavailable")
        val scanner = bluetooth.bluetoothLeScanner
        val accumulated = mutableMapOf<String, MutableSet<android.os.ParcelUuid>>()
        fun emit(bt: BluetoothDevice, name: String?, rssi: Int, uuids: Array<android.os.ParcelUuid>?) {
            val all = synchronized(accumulated) {
                accumulated.getOrPut(bt.address) { linkedSetOf() }.apply {
                    uuids?.let { addAll(it) }
                }.toTypedArray()
            }
            val match = runCatching { identify(bt, name, rssi, all) }.getOrNull()
            trySend(Discovery(bt.address, match))
        }
        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                try {
                    emit(result.device, result.scanRecord?.deviceName, result.rssi,
                        result.scanRecord?.serviceUuids?.toTypedArray())
                } catch (e: SecurityException) { close(e) }
            }
            override fun onScanFailed(errorCode: Int) {
                close(IllegalStateException("BLE scan failed: " + errorCode))
            }
        }
        val receiver = object : BroadcastReceiver() {
            @Suppress("DEPRECATION")
            override fun onReceive(context: Context, intent: Intent) {
                val bt = intent.getParcelableExtra<BluetoothDevice>(BluetoothDevice.EXTRA_DEVICE) ?: return
                if (intent.action == BluetoothDevice.ACTION_FOUND || intent.action == BluetoothDevice.ACTION_UUID) {
                    emit(bt, intent.getStringExtra(BluetoothDevice.EXTRA_NAME) ?: bt.name,
                        intent.getShortExtra(BluetoothDevice.EXTRA_RSSI, (-1).toShort()).toInt(), bt.uuids)
                }
            }
        }
        var registered = false
        var bleStarted = false
        var classicStarted = false
        try {
            ContextCompat.registerReceiver(context, receiver, IntentFilter().apply {
                addAction(BluetoothDevice.ACTION_FOUND)
                addAction(BluetoothDevice.ACTION_UUID)
            }, ContextCompat.RECEIVER_EXPORTED)
            registered = true
            if (scanner != null) {
                scanner.startScan(null, ScanSettings.Builder()
                    .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), callback)
                bleStarted = true
            }
            classicStarted = bluetooth.startDiscovery()
            check(bleStarted || classicStarted) { "No discovery method available" }
            awaitClose { }
        } finally {
            if (bleStarted) runCatching { scanner?.stopScan(callback) }
            if (classicStarted) runCatching { bluetooth.cancelDiscovery() }
            if (registered) runCatching { context.unregisterReceiver(receiver) }
        }
    }

    fun pairingKind(device: GBDevice): Int = device.deviceCoordinator.bondingStyle

    fun supportsNativePairing(device: GBDevice): Boolean =
        device.deviceCoordinator.isConnectable &&
            (known().any { it.address == device.address } || device.deviceCoordinator.pairingActivity == null)

    suspend fun connect(device: GBDevice, systemBond: Boolean = false, authKey: String = "") {
        check(hasPermissions()) { "Missing Bluetooth permission" }
        val bluetooth = adapter?.takeIf { it.isEnabled } ?: error("Bluetooth disabled")
        val existing = known().firstOrNull { it.address == device.address }
        val target = existing ?: device
        val coordinator = target.deviceCoordinator
        check(coordinator.isConnectable) { "Device is scan-only" }
        if (target.isInitialized || target.isConnecting || target.isInitializing) return
        if (existing == null) {
            check(coordinator.pairingActivity == null) { "Model requires a dedicated pairing adapter" }
            val style = coordinator.bondingStyle
            if (style == DeviceCoordinator.BONDING_STYLE_REQUIRE_KEY) {
                val prefs = GBApplication.getDeviceSpecificSharedPrefs(target.address)
                val key = authKey.trim().ifEmpty { prefs.getString("authkey", "") ?: "" }
                require(key.isNotEmpty() && coordinator.validateAuthKey(key)) { "Invalid or missing auth key" }
                prefs.edit().putString("authkey", key).apply()
            }
            if (style == DeviceCoordinator.BONDING_STYLE_BOND ||
                style == DeviceCoordinator.BONDING_STYLE_REQUIRE_KEY ||
                (style == DeviceCoordinator.BONDING_STYLE_ASK && systemBond)) {
                val bt = bluetooth.getRemoteDevice(target.address)
                if (bt.bondState != BluetoothDevice.BOND_BONDED) {
                    check(bt.bondState == BluetoothDevice.BOND_BONDING || bt.createBond()) { "System pairing could not start" }
                    val bonded = withTimeoutOrNull(45000L) {
                        while (bt.bondState == BluetoothDevice.BOND_BONDING) delay(300)
                        bt.bondState == BluetoothDevice.BOND_BONDED
                    } == true
                    check(bonded) { "System pairing incomplete" }
                }
            }
        }
        GBApplication.deviceService(target).connect(existing == null)
    }

    fun disconnect(device: GBDevice) {
        GBApplication.deviceService(device).disconnect()
    }
}
