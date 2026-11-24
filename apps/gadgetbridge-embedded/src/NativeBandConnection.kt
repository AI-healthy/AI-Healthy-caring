package org.aihealthy.shiyi.integration.embedded

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
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

    val adapter: BluetoothAdapter?
        get() = context.getSystemService(BluetoothManager::class.java)?.adapter

    fun permissions(): Array<String> =
        if (Build.VERSION.SDK_INT >= 31) arrayOf(
            Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT
        ) else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)

    fun hasPermissions(): Boolean = permissions().all {
        ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED
    }

    fun known(): List<GBDevice> = EmbeddedBandReader.bands().toList()

    fun state(device: GBDevice): State = State(device.address, device.name, device.isInitialized,
        device.isConnecting || device.isInitializing, device.isBusy)

    fun scan(): Flow<Found> = callbackFlow {
        check(hasPermissions()) { "Missing Bluetooth permission" }
        val scanner = adapter?.takeIf { it.isEnabled }?.bluetoothLeScanner
            ?: error("Bluetooth unavailable")
        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                try {
                    val name = result.scanRecord?.deviceName ?: result.device.name ?: return
                    if (!name.startsWith("honor band 4-", ignoreCase = true)) return
                    val candidate = GBDeviceCandidate(result.device, result.rssi.toShort(),
                        result.scanRecord?.serviceUuids?.toTypedArray())
                    candidate.refreshNameIfUnknown()
                    val device = DeviceType.HONORBAND4.deviceCoordinator
                        .createDevice(candidate, DeviceType.HONORBAND4)
                    device.setName(name)
                    trySend(Found(name, device.address, result.rssi, device))
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
