package org.aihealthy.shiyi.integration.embedded

import nodomain.freeyourgadget.gadgetbridge.GBApplication
import nodomain.freeyourgadget.gadgetbridge.impl.GBDevice
import java.util.UUID

/** Installation-local random stream identity. Never upload a hardware MAC as the stream key. */
object WearableDeviceScope {
    @Synchronized
    fun get(device: GBDevice): String {
        val prefs = GBApplication.getDeviceSpecificSharedPrefs(device.address)
        val existing = prefs.getString("shiyi_device_scope_v1", null)
        if (existing != null && existing.matches(Regex("[0-9a-f]{32}"))) return existing
        val fresh = UUID.randomUUID().toString().replace("-", "")
        check(prefs.edit().putString("shiyi_device_scope_v1", fresh).commit()) {
            "Could not persist wearable stream identity"
        }
        return fresh
    }
}
