package org.aihealthy.shiyi.integration.embedded

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import nodomain.freeyourgadget.gadgetbridge.GBApplication
import nodomain.freeyourgadget.gadgetbridge.database.DBHelper
import nodomain.freeyourgadget.gadgetbridge.devices.huami.HuamiConst
import nodomain.freeyourgadget.gadgetbridge.entities.MiBandActivitySampleDao
import nodomain.freeyourgadget.gadgetbridge.impl.GBDevice
import nodomain.freeyourgadget.gadgetbridge.model.ActivityKind
import nodomain.freeyourgadget.gadgetbridge.model.DeviceType
import org.aihealthy.shiyi.integration.wearable.HealthMetric
import org.aihealthy.shiyi.integration.wearable.HealthObservation
import org.aihealthy.shiyi.integration.wearable.WearableReader
import java.security.MessageDigest
import java.time.Duration
import java.time.Instant

/**
 * Raw minute-sample adapter for the pinned Huami legacy fetch protocol.
 * FetchActivityOperation writes one MiBandActivitySample per minute. Do not use
 * chart providers that interpolate gaps or carry forward activity classifications.
 * Hardware acceptance is still required for each model.
 */
class HuamiBandReader(private val band: GBDevice) : WearableReader {
    companion object {
        private val supported = setOf(DeviceType.MIBAND4, DeviceType.MIBAND5, DeviceType.MIBAND6)
        fun supports(band: GBDevice): Boolean = band.type in supported
    }

    private fun sample(metric: HealthMetric, value: Int, at: Long, start: Long?,
                       scope: String): HealthObservation {
        val key = listOf("huami-minute-v1", band.address, metric.wire, at, start).joinToString("|")
        val id = "gb-" + MessageDigest.getInstance("SHA-256")
            .digest(key.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it.toInt() and 0xff) }
        return HealthObservation(id, metric, value, Instant.ofEpochSecond(at),
            EmbeddedBandReader.ORIGIN, start?.let { Instant.ofEpochSecond(it) },
            EmbeddedBandReader.SOURCE, scope)
    }

    override suspend fun read(start: Instant, end: Instant): List<HealthObservation> =
        withContext(Dispatchers.IO) {
            require(supports(band))
            require(start < end && Duration.between(start, end) <= Duration.ofDays(7))
            val scope = WearableDeviceScope.get(band)
            GBApplication.acquireDB().use { db ->
                val session = db.daoSession
                val device = DBHelper.findDevice(band, session) ?: return@use emptyList()
                val rows = session.miBandActivitySampleDao.queryBuilder().where(
                    MiBandActivitySampleDao.Properties.DeviceId.eq(device.id),
                    MiBandActivitySampleDao.Properties.Timestamp.ge(Math.toIntExact(start.epochSecond)),
                    MiBandActivitySampleDao.Properties.Timestamp.le(Math.toIntExact(end.epochSecond))
                ).orderAsc(MiBandActivitySampleDao.Properties.Timestamp).list()
                val out = mutableListOf<HealthObservation>()
                for (row in rows) {
                    val a = row.timestamp.toLong()
                    val b = a + 60
                    val kind = HuamiConst.toActivityKind(row.rawKind and 0x0f)
                    if (kind == ActivityKind.NOT_WORN || a > end.epochSecond) continue
                    val hr = row.heartRate
                    if (hr in 1..254) out += sample(HealthMetric.HEART_RATE, hr, a, null, scope)
                    if (b > end.epochSecond) continue
                    // Steps are the byte count in the minute record; do not impute gaps.
                    if (row.steps in 0..255) {
                        out += sample(HealthMetric.STEPS, row.steps, b, a, scope)
                    }
                    // Only explicitly classified sleep minutes; no carried-forward or inferred stage.
                    if (kind == ActivityKind.LIGHT_SLEEP || kind == ActivityKind.DEEP_SLEEP) {
                        out += sample(HealthMetric.SLEEP, 1, b, a, scope)
                    }
                }
                out.distinctBy { it.id }.sortedBy { it.observedAt }
            }
        }
}
