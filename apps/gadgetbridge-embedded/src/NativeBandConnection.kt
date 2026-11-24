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
import android.content.pm.PackageManager
import android.os.Build
import android.location.LocationManager
import java.util.Locale
import androidx.core.content.ContextCompat
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import nodomain.freeyourgadget.gadgetbridge.GBApplication
import nodomain.freeyourgadget.gadgetbridge.impl.GBDevice
import nodomain.freeyourgadget.gadgetbridge.impl.GBDeviceCandidate
import nodomain.freeyourgadget.gadgetbridge.model.DeviceType

/** Honor Band 4 uses the upstream coordinator's BONDING_STYLE_NONE. */
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

    fun known(): List<GBDevice> = EmbeddedBandReader.bands().toList()

    fun state(device: GBDevice): State = State(device.address, device.name, device.isInitialized,
        device.isConnecting || device.isInitializing, device.isBusy)

    private fun honorName(name: String?): Boolean = name != null &&
        Regex("^honor[\\\\s_-]*band[\\\\s_-]*4(?:$|[\\\\s_-].*)",
            RegexOption.IGNORE_CASE).matches(name.trim())

    private fun foundDevice(bt: BluetoothDevice, name: String, rssi: Int,
                            uuids: Array<android.os.ParcelUuid>? = null): Found {
        val candidate = GBDeviceCandidate(bt, rssi.toShort(), uuids)
        candidate.refreshNameIfUnknown()
        val device = DeviceType.HONORBAND4.deviceCoordinator
            .createDevice(candidate, DeviceType.HONORBAND4)
        device.setName(name)
        return Found(name, device.address, rssi, device)
    }

    fun bonded(): List<Found> {
        check(hasPermissions())
        return adapter?.bondedDevices.orEmpty().mapNotNull { bt ->
            val name = bt.name
            if (name != null && honorName(name)) foundDevice(bt, name, -1) else null
        }
    }

    /** Explicit user-supplied address of their own Honor Band 4; no guessing or automatic connection. */
    fun manual(address: String): Found {
        check(hasPermissions())
        val normalized = address.trim().uppercase(Locale.ROOT)
        require(BluetoothAdapter.checkBluetoothAddress(normalized)) { "Invalid Bluetooth address" }
        val bt = adapter?.takeIf { it.isEnabled }?.getRemoteDevice(normalized)
            ?: error("Bluetooth unavailable")
        val name = bt.name
        require(name.isNullOrBlank() || honorName(name)) { "Address belongs to another named device" }
        return foundDevice(bt, name?.takeIf { honorName(it) } ?: "HONOR Band 4", -1)
    }

    fun scan(): Flow<Discovery> = callbackFlow {
        check(hasPermissions()) { "Missing Bluetooth permission" }
        val scanner = adapter?.takeIf { it.isEnabled }?.bluetoothLeScanner
            ?: error("Bluetooth unavailable")
        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                try {
                    val name = listOfNotNull(result.scanRecord?.deviceName, result.device.name)
                        .firstOrNull { honorName(it) }
                    val match = name?.let { foundDevice(result.device, it, result.rssi,
                        result.scanRecord?.serviceUuids?.toTypedArray()) }
                    // Count all advertisements locally; never display/upload unrelated addresses.
                    trySend(Discovery(result.device.address, match))
                } catch (e: SecurityException) {
                    close(e)
                }
            }

            override fun onScanFailed(errorCode: Int) {
                close(IllegalStateException("BLE scan failed: " + errorCode))
            }
        }
        scanner.startScan(null, ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), callback)
        awaitClose { runCatching { scanner.stopScan(callback) } }
    }

    fun connect(device: GBDevice) {
        check(hasPermissions()) { "Missing Bluetooth permission" }
        check(adapter?.isEnabled == true) { "Bluetooth disabled" }
        val existing = known().firstOrNull { it.address == device.address }
        val target = existing ?: device
        if (target.isInitialized || target.isConnecting || target.isInitializing) return
        GBApplication.deviceService(target).connect(existing == null)
    }

    fun disconnect(device: GBDevice) {
        GBApplication.deviceService(device).disconnect()
    }
}
